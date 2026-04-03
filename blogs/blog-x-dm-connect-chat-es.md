# DMs de X (Twitter) y Amazon Connect Chat

<table>
<tr>
<td width="50%">

_Aprende cómo conectar los Mensajes Directos de X (Twitter) con Amazon Connect Chat para una atención al cliente fluida. Esta guía paso a paso cubre la arquitectura completa usando AWS CDK, AWS Lambda, Amazon API Gateway, Amazon DynamoDB y Amazon Connect. Desde recibir DMs de clientes hasta enrutarlos a agentes, reenviar respuestas de agentes a X y manejar archivos adjuntos en ambas direcciones — todo con gestión automática de sesiones, validación CRC de webhooks y caché de perfiles de usuario vía el SDK de Tweepy._

</td>
<td width="50%">

![Demo](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/x-dm-connect-chat/demo_x_connect_chat.gif)

</td>
</tr>
</table>

Tus clientes ya están en X. Siguen tu marca, interactúan con tus publicaciones, y cuando necesitan ayuda — envían un DM. Si tu equipo de soporte tiene que alternar entre X y su herramienta de contact center, estás perdiendo tiempo y contexto.

En este blog, aprenderás cómo conectar los Mensajes Directos de X directamente a Amazon Connect Chat, para que tus agentes manejen conversaciones de X desde el mismo workspace que usan para todos los demás canales. Sin cambiar de app, sin copiar y pegar, sin mensajes perdidos.

Revisa el código en [Github](https://github.com/aws-samples/sample-amazon-connect-social-integration)

## Qué vas a construir

Un puente de mensajería bidireccional entre DMs de X y Amazon Connect que:

1. Recibe DMs entrantes de X vía el webhook del Account Activity API y los enruta a Amazon Connect Chat
2. Reenvía las respuestas de los agentes desde Amazon Connect de vuelta a X a través del SDK de Tweepy
3. Gestiona sesiones de chat automáticamente — creando nuevas, reutilizando activas y limpiando las expiradas
4. Cachea perfiles de usuario de X (nombre, username, imagen de perfil) en DynamoDB para reducir llamadas al API
5. Maneja archivos adjuntos en ambas direcciones — imágenes, videos y GIFs de clientes, e imágenes y videos de agentes
6. Previene loops echo filtrando mensajes enviados por tu propia cuenta de X

El resultado final: los agentes ven las conversaciones de X como contactos de chat regulares en su workspace de Amazon Connect, con el nombre y la información de perfil del cliente.

## Arquitectura

![Diagrama de Arquitectura](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/x-dm-connect-chat/x-connect-chat.svg)

Así funciona el flujo:

1. Un cliente envía un DM en X. El Account Activity API entrega el evento webhook a un endpoint de API Gateway
2. La Lambda del Inbound Handler valida el webhook (desafío CRC), parsea el mensaje y busca o crea una sesión de Amazon Connect Chat
3. El perfil de X del cliente (si no está presente en el request) se obtiene vía el SDK de Tweepy y se cachea en DynamoDB
4. Los mensajes de texto y archivos adjuntos se envían a la sesión de Connect Chat vía el Participant API
5. Cuando un agente responde, Amazon Connect publica el evento a un topic SNS vía contact streaming
6. La Lambda del Outbound Handler recibe el evento SNS, busca el ID de usuario de X del cliente y envía la respuesta como DM a través del SDK de Tweepy

## Entrante: X → Amazon Connect

Cuando un cliente envía un DM a tu cuenta business de X, el flujo entrante maneja todo, desde la validación del webhook hasta la entrega del mensaje.

### 1. Validación CRC del Webhook

X usa un Challenge-Response Check (CRC) para verificar la propiedad del webhook — esto es fundamentalmente diferente del enfoque de Meta usado en las integraciones de Instagram y Facebook Messenger. En lugar de comparar un string secreto compartido, X envía un `crc_token` que debe ser hasheado con tu Consumer Secret usando HMAC-SHA256:

```python
def compute_crc_response(crc_token, consumer_secret):
    digest = hmac.new(
        consumer_secret.encode('utf-8'),
        crc_token.encode('utf-8'),
        hashlib.sha256
    ).digest()
    
    encoded_hash = base64.b64encode(digest).decode('utf-8')
    return {"response_token": f"sha256={encoded_hash}"}
```

X envía este desafío tanto durante el registro inicial del webhook como periódicamente después para re-validar. La Lambda lo maneja automáticamente en cada solicitud GET.

### 2. Parseo de Mensajes y Prevención de Echo

Para solicitudes POST (eventos DM reales), la clase `XService` parsea el payload `direct_message_events`. Cada evento contiene el ID del remitente, ID del destinatario, contenido de texto y cualquier adjunto multimedia:

```python
class XMessage:
    def __init__(self, event_data):
        message_create = event_data.get('message_create', {})
        message_data = message_create.get('message_data', {})
        self.sender_id = message_create.get('sender_id')
        self.text = message_data.get('text')
        self.recipient_id = message_create.get('target', {}).get('recipient_id')
        
        # Parsear adjunto si está presente
        self.attachment = message_data.get('attachment')
        if self.attachment and self.attachment.get('type') == 'media':
            media = self.attachment.get('media', {})
            self.attachment_url = media.get('media_url_https')
            self.attachment_type = media.get('type')  # photo, animated_gif, video
```

El servicio filtra mensajes enviados por tu propio ID de cuenta de X para prevenir loops echo — cuando tu cuenta envía una respuesta, X también la entrega como evento webhook.

### 3. Obtención y Caché de Perfiles de Usuario

Los payloads del webhook de X incluyen datos de perfil de usuario inline en un diccionario `users`, que el servicio extrae primero. Para perfiles faltantes, recurre a una búsqueda de tres niveles:

```python
def get_user_profile(self, user_id):
    # Verificar caché en memoria primero
    if user_id in self.user_profiles:
        return self.user_profiles[user_id]

    # Verificar tabla de usuarios en DynamoDB
    if USERS_TABLE_NAME:
        users_table = TableService(table_name=USERS_TABLE_NAME)
        db_profile = users_table.get_item({"id": user_id})
        if db_profile:
            return db_profile

    # Obtener del X API vía Tweepy como último recurso
    client = tweepy.Client(
        consumer_key=credentials.get('consumer_key'),
        consumer_secret=credentials.get('consumer_secret'),
        access_token=credentials.get('access_token'),
        access_token_secret=credentials.get('access_token_secret')
    )
    response = client.get_user(id=user_id, user_fields=['name', 'username', 'profile_image_url'])
    # ... cachear en DynamoDB con TTL de 7 días
```

El perfil incluye `name`, `username` y `profile_image_url`. Los perfiles se cachean en una tabla DynamoDB con un TTL de 7 días, así que las conversaciones repetidas se saltan la llamada al API.

### 4. Gestión de Sesiones

El handler verifica en DynamoDB si existe una sesión de chat activa usando el ID de usuario de X del remitente:

- Si existe una sesión, envía el mensaje usando el `connectionToken` almacenado. Si el token expiró (AccessDeniedException), crea automáticamente una nueva sesión.
- Si no existe sesión, llama a `StartChatContact` para crear un nuevo Amazon Connect Chat, inicia contact streaming al topic SNS, crea una conexión de participante y almacena todo en DynamoDB.

Los atributos de contacto incluyen el nombre del canal ("X"), el ID del cliente y el nombre de display del cliente — facilitando identificar el canal de origen en Contact Flows y enrutamiento de agentes.

### 5. Manejo de Archivos Adjuntos (Entrante)

Cuando un cliente envía una imagen, GIF o video, el handler lo descarga del CDN de X y lo sube a la sesión de Connect Chat. Las URLs de media de X vienen en dos variantes:

- `pbs.twimg.com` — accesible públicamente, descarga directa
- `ton.twitter.com` — requiere autenticación OAuth 1.0a (usando `requests_oauthlib`)

La carga usa el flujo de tres pasos del Participant API: `start_attachment_upload` → PUT a URL pre-firmada → `complete_attachment_upload`. Si algo falla, el handler envía la URL del media como mensaje de texto.

Para adjuntos que incluyen un caption, el texto se limpia eliminando el enlace `t.co` que X agrega automáticamente al cuerpo del mensaje.

## Saliente: Amazon Connect → X

Cuando un agente responde desde el workspace de Amazon Connect, el flujo saliente entrega el mensaje de vuelta a X.

### 1. Eventos de Streaming vía SNS

Amazon Connect publica eventos de streaming de chat a un topic SNS. La Lambda del Outbound Handler se suscribe a este topic y procesa tres tipos de eventos:

- `MESSAGE` — mensajes de texto del agente
- `ATTACHMENT` — archivos adjuntos enviados por el agente
- `EVENT` — eventos de unión/salida de participantes y fin de chat

Los mensajes del rol `CUSTOMER` se omiten para evitar procesar los propios mensajes del cliente nuevamente.

### 2. Envío de Mensajes de Texto

Para mensajes de texto con visibilidad `CUSTOMER` o `ALL`, el handler busca el ID de usuario de X del cliente en DynamoDB y envía la respuesta vía el API v2 de Tweepy:

```python
def send_x_text(credentials, text, recipient_id):
    client = tweepy.Client(
        consumer_key=credentials["consumer_key"],
        consumer_secret=credentials["consumer_secret"],
        access_token=credentials["access_token"],
        access_token_secret=credentials["access_token_secret"],
    )
    response = client.create_direct_message(
        participant_id=recipient_id,
        text=text,
    )
    return response
```

### 3. Envío de Archivos Adjuntos

Cuando un agente envía un archivo desde el widget de Connect Chat, el handler obtiene una URL firmada del adjunto, lo descarga y lo sube a X vía el endpoint de media upload v1.1 (OAuth 1.0a). El media ID se usa luego para enviar un DM con el adjunto:

| Tipo MIME | Categoría de media X | Método de carga |
|---|---|---|
| `image/jpeg`, `image/png`, `image/webp` | `dm_image` | `media_upload` |
| `image/gif` | `dm_gif` | `chunked_upload` |
| `video/mp4` | `dm_video` | `chunked_upload` |
| todo lo demás | — | Enviado como enlace de texto |

Los DMs de X solo soportan imágenes y videos como media nativo. Los tipos no soportados (PDFs, documentos, etc.) se envían como URLs en texto plano para que el cliente aún tenga acceso al contenido.

### 4. Limpieza de Sesiones

Cuando un participante sale o el chat termina, el handler elimina el registro de conexión de DynamoDB para que el próximo mensaje entrante inicie una sesión nueva.

## Tipos de Mensajes Soportados

| Dirección | Texto | Imágenes | Videos | GIFs |
|---|---|---|---|---|
| Entrante (cliente → agente) | ✅ | ✅ | ✅ | ✅ |
| Saliente (agente → cliente) | ✅ | ✅ | ✅ | ✅ |

Los tipos de media no soportados (PDFs, documentos, etc.) se envían como enlaces de texto plano en la dirección saliente.

## Qué se Despliega

| Recurso | Servicio | Propósito |
|---|---|---|
| Endpoint `/webhooks` (GET & POST) | API Gateway | Recibe desafíos CRC de X (GET) y eventos DM entrantes (POST) |
| Inbound Handler | Lambda | Procesa eventos DM de X y los enruta a Amazon Connect Chat |
| Outbound Handler | Lambda | Envía respuestas de agentes de vuelta a X como DMs vía el SDK de Tweepy |
| Tabla Active Connections | DynamoDB | Rastrea sesiones de chat abiertas (`contactId` PK, `userId` GSI) |
| Tabla X Users | DynamoDB | Cachea perfiles de usuario de X (expiración por TTL, 7 días) |
| Topic `messages_out` | SNS | Entrega eventos de streaming de Amazon Connect al Outbound Handler |
| `x-dm-credentials` | Secrets Manager | Almacena credenciales OAuth 1.0a del X API (Consumer Key, Consumer Secret, Access Token, Access Token Secret) |
| `/x/dm/config` | SSM Parameter Store | Contiene instance ID de Connect, contact flow ID e ID de cuenta de X |
| `/x/dm/webhook/url` | SSM Parameter Store | Almacena la URL del callback de API Gateway desplegado |

## Estimación de Costos

Escenario de ejemplo: 1,000 conversaciones por mes, promediando 10 mensajes cada una (5 entrantes + 5 salientes), totalizando 10,000 mensajes.

| Componente | Costo Mensual Estimado | Notas |
|---|---|---|
| Infraestructura (API GW, Lambda, DynamoDB, SNS, Secrets Manager) | ~$0.71 | Despreciable a esta escala |
| Amazon Connect Chat (Entrante) | $20.00 | 5,000 msgs × $0.004/msg |
| Amazon Connect Chat (Saliente) | $20.00 | 5,000 msgs × $0.004/msg |
| X API — DMs Salientes | ~$50.00 | 5,000 envíos de DM × ~$0.01/request |
| **Total** | **~$90.71** | |

El X API usa precios de pago por uso basados en créditos. El costo por endpoint mostrado arriba es aproximado — las tarifas reales se muestran en la [Consola de Desarrollador de X](https://console.x.com/) y pueden cambiar. Consulta los [precios de Amazon Connect](https://aws.amazon.com/connect/pricing/) y los [precios del X API](https://developer.x.com/en/products/twitter-api) para tarifas actuales.

Para reducir costos de Connect Chat en conversaciones de alto volumen, considera agregar una [capa de buffering de mensajes](https://github.com/aws-samples/sample-whatsapp-end-user-messaging-connect-chat/tree/main/whatsapp-eum-connect-chat) para agregar mensajes consecutivos rápidos.

## Prerrequisitos de Despliegue

Antes de comenzar necesitarás:

### Cuenta de Desarrollador de X y Credenciales API

Necesitas una cuenta de desarrollador de X con al menos el tier Pay-Per-Use, y cuatro credenciales OAuth 1.0a (Consumer Key, Consumer Secret, Access Token, Access Token Secret).

Consulta la [Guía de Configuración de X](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/x_setup.md) para instrucciones detalladas paso a paso sobre cómo crear tu app, configurar permisos y generar credenciales.

⚠️ Importante: El tier gratuito no incluye entrega de DMs basada en webhooks. Necesitas el tier Pay-Per-Use.

### Una Instancia de Amazon Connect

Necesitas una instancia de Amazon Connect. Si aún no tienes una, puedes [seguir esta guía](https://docs.aws.amazon.com/connect/latest/adminguide/amazon-connect-instances.html) para crear una.

Necesitarás el **INSTANCE_ID** de tu instancia. Lo puedes encontrar en la consola de Amazon Connect o en el ARN de la instancia:

`arn:aws:connect:<region>:<account_id>:instance/INSTANCE_ID`

### Un Flujo de Chat para Manejar Mensajes

Crea o ten listo el flujo de contacto que define la experiencia del usuario. [Sigue esta guía](https://docs.aws.amazon.com/connect/latest/adminguide/create-contact-flow.html) para crear un Inbound Contact Flow. El más sencillo funcionará.

Recuerda publicar el flujo.

![Flujo Simple](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/flow_simple.png)

Toma nota del **INSTANCE_ID** y **CONTACT_FLOW_ID** en la pestaña de Detalles. Los valores están en el ARN del flujo:

`arn:aws:connect:<region>:<account_id>:instance/INSTANCE_ID/contact-flow/CONTACT_FLOW_ID`

(consulta los [Prerrequisitos de Amazon Connect](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/general_connect.md) para más detalles)


## Despliegue con AWS CDK

⚠️ Despliega en la misma región donde tu instancia de Amazon Connect está configurada.

### 1. Clona el repositorio y navega al proyecto

```bash
git clone https://github.com/aws-samples/sample-amazon-connect-social-integration.git
cd sample-amazon-connect-social-integration/x-dm-connect-chat
```

### 2. Despliega con CDK

Sigue las instrucciones en la [Guía de Despliegue CDK](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/general_cdk_deploy.md) para configuración del entorno y comandos de despliegue.

## Configuración Post-despliegue

Después del despliegue, se necesitan tres pasos de configuración:

1. **Actualizar Credenciales del X API** — El stack crea un secreto en Secrets Manager llamado `x-dm-credentials` con valores placeholder. Actualízalo con tu Consumer Key, Consumer Secret, Access Token y Access Token Secret reales.

2. **Actualizar Configuración SSM** — Actualiza el parámetro SSM `/x/dm/config` con tu `instance_id` de Amazon Connect, `contact_flow_id` y el `x_account_id` numérico de tu cuenta de X.

3. **Registrar el Webhook y Suscribirse** — Registra la URL de tu API Gateway desplegado con el Account Activity API de X y suscribe tu cuenta business para recibir eventos DM. El Inbound Handler responde a los desafíos CRC automáticamente.

Para instrucciones detalladas de cada paso, incluyendo cómo encontrar tu `x_account_id` y registrar el webhook, consulta el [README del proyecto](https://github.com/aws-samples/sample-amazon-connect-social-integration/tree/main/x-dm-connect-chat) y la [Guía de Configuración de X](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/x_setup.md).

## Pruebas

Ve a tu instancia de Amazon Connect y [abre el Contact Control Panel (CCP)](https://docs.aws.amazon.com/connect/latest/adminguide/launch-ccp.html).

<div align="center">
<video src="https://github.com/user-attachments/assets/3fe667d9-1887-4acb-8ccf-3596d5c562a4" width="540" controls></video>
</div>

Prueba estos escenarios:

- Envía un DM a tu cuenta business de X desde otra cuenta de X — debería aparecer como un nuevo contacto de chat en el CCP
- Responde desde el CCP — la respuesta debería llegar a los DMs de X del cliente
- Envía una imagen desde X — debería aparecer como un adjunto de imagen en el chat del agente
- Desde el lado del agente, envía una imagen — debería aparecer en los DMs de X del cliente
- Intenta enviar un documento desde el lado del agente — debería llegar como enlace en los DMs del cliente

## Consideraciones Importantes sobre X

### DMs Encriptados

X soporta Mensajes Directos con encriptación de extremo a extremo (E2EE). Sin embargo, **los DMs encriptados no son accesibles vía el X API**. Esta integración solo procesa DMs estándar (no encriptados). Si una conversación está encriptada, el webhook no recibirá esos eventos de mensaje.

### Tier Pay-Per-Use

- El tier **Pay-Per-Use** es requerido para acceso al Account Activity API. El tier gratuito no incluye entrega de DMs basada en webhooks.
- Revisa los [precios del X API](https://developer.x.com/en/products/twitter-api) para detalles y costos actuales.

### Re-validación CRC

- X periódicamente re-envía desafíos CRC para verificar que tu webhook sigue siendo válido. El Inbound Handler maneja esto automáticamente, pero asegúrate de que las credenciales en Secrets Manager permanezcan válidas y la función Lambda siga desplegada.

### Credenciales OAuth 1.0a

- Las cuatro credenciales (Consumer Key, Consumer Secret, Access Token, Access Token Secret) deben permanecer válidas. Si regeneras cualquier credencial en el Portal de Desarrollador de X, actualiza el secreto en Secrets Manager inmediatamente.
- El Access Token y Access Token Secret están vinculados a la cuenta de usuario de X específica que posee la app. Asegúrate de que sea la cuenta business que debe recibir y enviar DMs.

### Límites de Tasa

- El X API aplica límites de tasa en los endpoints de DM. El Account Activity API tiene sus propios límites en registros de webhooks y validaciones CRC.
- Monitorea tu uso en el dashboard del [Portal de Desarrollador de X](https://developer.x.com/).

## Próximos Pasos

Esta solución maneja el flujo principal de mensajería X DM-a-Connect. Algunas ideas para extenderla:

- Usar Amazon Bedrock para analizar imágenes entrantes y dar contexto a los agentes antes de que respondan
- Usar [Amazon Connect AI Agents](https://docs.aws.amazon.com/connect/latest/adminguide/agentic-self-service.html) para autoservicio agéntico, permitiendo a los clientes resolver problemas comunes sin esperar a un agente humano
- Combinar con la [integración de Instagram DM](https://github.com/aws-samples/sample-amazon-connect-social-integration/tree/main/instagram-dm-connect-chat) y la [integración de Facebook Messenger](https://github.com/aws-samples/sample-amazon-connect-social-integration/tree/main/facebook-messenger-connect-chat) para manejar todos los canales sociales desde una sola instancia de Amazon Connect

### Aprovechar Amazon Connect Customer Profiles

Esta solución ya obtiene datos del perfil de X (nombre, username, imagen de perfil) y los pasa como atributos de contacto. Puedes ir más allá integrando con [Amazon Connect Customer Profiles](https://docs.aws.amazon.com/connect/latest/adminguide/customer-profiles.html) para dar a los agentes una vista unificada del cliente a través de canales. Luego en tu Contact Flow, usa el [bloque Customer Profiles](https://docs.aws.amazon.com/connect/latest/adminguide/customer-profiles-block.html) para recuperar el perfil y mostrarlo en el workspace del agente. El agente ve el nombre del cliente, su handle de X y cualquier historial de interacciones previas — todo antes de escribir una respuesta.

## Recursos

- [Repositorio del Proyecto](https://github.com/aws-samples/sample-amazon-connect-social-integration)
- [Guía de Administrador de Amazon Connect](https://docs.aws.amazon.com/connect/latest/adminguide/what-is-amazon-connect.html)
- [Documentación del X API](https://developer.x.com/en/docs)
- [X Account Activity API](https://developer.x.com/en/docs/twitter-api/enterprise/account-activity-api/overview)
- [Documentación de Tweepy](https://docs.tweepy.org/)
- [Guía de Configuración de X](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/x_setup.md)
