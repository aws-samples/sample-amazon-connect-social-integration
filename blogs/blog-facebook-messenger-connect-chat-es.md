# Facebook Messenger & Amazon Connect Chat

<table>
<tr>
<td width="50%">

_Aprende cómo conectar Facebook Messenger con Amazon Connect Chat para una atención al cliente fluida. Esta guía paso a paso cubre la arquitectura completa usando AWS CDK, AWS Lambda, Amazon API Gateway, Amazon DynamoDB y Amazon Connect. Desde recibir mensajes de clientes hasta enrutarlos a agentes, reenviar respuestas de agentes a Messenger y manejar archivos adjuntos en ambas direcciones — todo con gestión automática de sesiones, prevención de loops echo y caché de perfiles de usuario vía Graph API._

</td>
<td width="50%">

![Demo](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/facebook-messenger-connect-chat/demo_messenger_connect_chat.gif)

</td>
</tr>
</table>


Facebook Messenger tiene más de mil millones de usuarios activos. Muchos de ellos ya están enviando mensajes a tu Página de Facebook con preguntas sobre productos, estado de pedidos o solicitudes de soporte. Si tus agentes tienen que alternar entre Meta Business Suite y su contact center, se pierde contexto y los tiempos de respuesta se resienten.

En este blog, aprenderás cómo conectar Facebook Messenger directamente a Amazon Connect Chat, para que tus agentes manejen conversaciones de Messenger desde el mismo workspace que usan para todos los demás canales. Los mensajes fluyen en ambas direcciones — incluyendo imágenes, documentos y archivos — con gestión automática de sesiones y enriquecimiento de perfiles de usuario.

Revisa el código en [Github](https://github.com/aws-samples/sample-amazon-connect-social-integration)


## Qué vas a construir

Un puente de mensajería bidireccional entre Facebook Messenger y Amazon Connect que:

1. Recibe mensajes entrantes de Messenger vía webhooks de Meta y los enruta a Amazon Connect Chat
2. Reenvía las respuestas de los agentes desde Amazon Connect de vuelta a Messenger a través del Send API
3. Gestiona sesiones de chat automáticamente — creando nuevas, reutilizando activas y limpiando las expiradas
4. Obtiene y cachea perfiles de usuario de Messenger (nombre, apellido, foto de perfil) vía Graph API
5. Maneja archivos adjuntos en ambas direcciones — imágenes y archivos de clientes, e imágenes y archivos de agentes
6. Previene loops echo filtrando mensajes enviados por tu propia Página

El resultado final: los agentes ven las conversaciones de Messenger como contactos de chat regulares en su workspace de Amazon Connect, con el nombre real del cliente.

## Arquitectura

![Diagrama de Arquitectura](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/facebook-messenger-connect-chat/facebook-messengar-chat.svg)

Así funciona el flujo:

1. Un cliente envía un mensaje en Facebook Messenger. Meta entrega el evento webhook a un endpoint de API Gateway
2. La Lambda del Inbound Handler valida el webhook, parsea el mensaje y busca o crea una sesión de Amazon Connect Chat
3. El perfil de Messenger del cliente se obtiene vía Graph API y se cachea en DynamoDB
4. Los mensajes de texto y archivos adjuntos se envían a la sesión de Connect Chat vía el Participant API
5. Cuando un agente responde, Amazon Connect publica el evento a un topic SNS vía contact streaming
6. La Lambda del Outbound Handler recibe el evento SNS, busca el Page-Scoped ID (PSID) del cliente y envía la respuesta a través del Messenger Send API

## Entrante: Messenger → Amazon Connect

Cuando un cliente envía un mensaje a tu Página de Facebook, el flujo entrante maneja todo, desde la validación del webhook hasta la entrega del mensaje.

### 1. Validación del Webhook y Parseo de Mensajes

Meta envía eventos webhook a tu endpoint `/messages` de API Gateway. La Lambda maneja solicitudes GET para verificación del webhook — Meta envía los parámetros `hub.mode`, `hub.verify_token` y `hub.challenge` que deben ser validados y devueltos.

Para solicitudes POST, la clase `MessengerService` parsea el payload del webhook. Los webhooks de Messenger llegan con `object: "page"` y contienen entries con datos de mensajería:

```python
class MessengerMessage:
    def __init__(self, messaging_data):
        self.sender_id = messaging_data.get('sender', {}).get('id')
        self.recipient_id = messaging_data.get('recipient', {}).get('id')
        self.timestamp = messaging_data.get('timestamp')
        
        message_data = messaging_data.get('message', {})
        self.message_id = message_data.get('mid')
        self.text = message_data.get('text')
        self.attachments = message_data.get('attachments', [])
        
        if self.text:
            self.message_type = 'text'
        elif len(self.attachments):
            self.message_type = 'attachment'
        else:
            self.message_type = 'unknown'
```

El servicio filtra mensajes enviados por tu propio Page ID para prevenir loops echo — cuando tu Página envía una respuesta, Meta también la entrega como evento webhook, y sin este filtro tendrías un ciclo infinito.

### 2. Obtención y Caché de Perfiles de Usuario

Antes de enrutar el mensaje a Connect, el handler obtiene el perfil de Messenger del remitente usando el Graph API. A diferencia de Instagram (que retorna un solo campo `name`), Messenger proporciona `first_name` y `last_name` por separado:

```python
def get_user_profile(self, psid, fields=None):
    # Verificar caché en memoria primero
    if psid in self.user_profiles:
        return self.user_profiles[psid]

    # Verificar tabla de usuarios en DynamoDB
    if USERS_TABLE_NAME:
        users_table = TableService(table_name=USERS_TABLE_NAME)
        db_profile = users_table.get_item({"id": psid})
        if db_profile:
            return db_profile

    # Obtener del Graph API
    if fields is None:
        fields = ['first_name', 'last_name', 'profile_pic']
    
    params = {'fields': ','.join(fields), 'access_token': self.access_token}
    url = f"https://graph.facebook.com/v24.0/{psid}?{urlencode(params)}"
    # ... obtener y cachear en DynamoDB con TTL de 7 días
```

El nombre para mostrar se construye concatenando `first_name` y `last_name`, y esto es lo que el agente ve en el widget de Connect Chat.

### 3. Gestión de Sesiones

El handler verifica en DynamoDB si existe una sesión de chat activa usando el PSID (Page-Scoped ID) del remitente:

- Si existe una sesión, envía el mensaje usando el `connectionToken` almacenado. Si el token expiró (AccessDeniedException), crea automáticamente una nueva sesión y limpia el registro anterior.
- Si no existe sesión, llama a `StartChatContact` para crear un nuevo Amazon Connect Chat, inicia contact streaming al topic SNS, crea una conexión de participante y almacena todo en DynamoDB.

Los atributos de contacto incluyen el nombre del canal ("Messenger"), el ID del cliente (PSID) y el nombre para mostrar del cliente — facilitando identificar el canal de origen en Contact Flows y enrutamiento de agentes.

```python
attributes = {
    "Channel": "Messenger",
    "customerId": userId,
    "customerName": userName,
}

start_chat_response = self.connect.start_chat_contact(
    InstanceId=self.instance_id,
    ContactFlowId=self.contact_flow_id,
    Attributes=attributes,
    ParticipantDetails={"DisplayName": userName},
    InitialMessage={"ContentType": "text/plain", "Content": message},
    ChatDurationInMinutes=self.chat_duration_minutes,
)
```

### 4. Manejo de Archivos Adjuntos (Entrante)

Cuando un cliente envía una imagen, video, audio o archivo en Messenger, los datos del adjunto incluyen un `type` y un `payload.url` apuntando al CDN de Meta. El handler descarga el contenido del archivo y lo sube a la sesión de Connect Chat:

```python
def attachment_message_handler(message, connect_chat_service, table_service, user_name, sender_profile):
    # Asegurar que existe una sesión de chat (crear una si es necesario)
    # ...
    
    for attachment in message.attachments:
        att_url = attachment.get('payload', {}).get('url')
        
        # Descargar del CDN de Messenger
        file_bytes, content_type = download_attachment(att_url)
        
        # Subir a Connect Chat vía Participant API
        attachment_id, error = connect_chat_service.attach_file(
            fileContents=file_bytes,
            fileName=get_attachment_filename(attachment),
            fileType=content_type,
            ConnectionToken=connection_token
        )
```

La carga usa el mismo flujo de tres pasos del Participant API: `start_attachment_upload` → PUT a URL pre-firmada → `complete_attachment_upload`. Si algo falla, el handler envía la URL del CDN como mensaje de texto como fallback.

## Saliente: Amazon Connect → Messenger

Cuando un agente responde desde el workspace de Amazon Connect, el flujo saliente entrega el mensaje de vuelta a Messenger.

### 1. Eventos de Streaming vía SNS

Amazon Connect publica eventos de streaming de chat a un topic SNS. La Lambda del Outbound Handler se suscribe a este topic y procesa tres tipos de eventos:

- `MESSAGE` — mensajes de texto del agente
- `ATTACHMENT` — archivos adjuntos enviados por el agente
- `EVENT` — eventos de unión/salida de participantes y fin de chat

Los mensajes del rol `CUSTOMER` se omiten para evitar procesar los propios mensajes del cliente nuevamente.

### 2. Envío de Mensajes de Texto

Para mensajes de texto con visibilidad `CUSTOMER` o `ALL`, el handler busca el PSID del cliente en DynamoDB y envía la respuesta vía el Messenger Send API:

```python
def send_messenger_text(access_token, text_message, recipient_id):
    url = f"https://graph.facebook.com/v24.0/me/messages"
    
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text_message},
    }
    
    url_with_token = f"{url}?access_token={quote(access_token)}"
    # POST al Messenger Send API
```

### 3. Envío de Archivos Adjuntos

Cuando un agente envía un archivo desde el widget de Connect Chat, el handler obtiene una URL firmada del adjunto y lo reenvía a Messenger como mensaje multimedia. El tipo MIME determina el tipo de adjunto de Messenger:

| Prefijo MIME | Tipo Messenger |
|---|---|
| `image/*` | `image` |
| `video/*` | `video` |
| `audio/*` | `audio` |
| todo lo demás | `file` |

```python
def send_messenger_attachment(access_token, attachment_url, mime_type, recipient_id):
    attachment_type = get_attachment_type(mime_type)  # image, video, audio, o file
    
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": attachment_type,
                "payload": {"url": attachment_url, "is_reusable": True}
            }
        },
    }
    # POST al Messenger Send API
```

El flag `is_reusable: True` le dice a Meta que cachee el adjunto, lo que puede acelerar la entrega si el mismo archivo se envía a múltiples destinatarios.

### 4. Limpieza de Sesiones

Cuando un participante sale o el chat termina, el handler elimina el registro de conexión de DynamoDB para que el próximo mensaje entrante inicie una sesión nueva.

## Tipos de Mensajes Soportados

| Dirección | Texto | Imágenes | Videos | Audio | Archivos |
|---|---|---|---|---|---|
| Entrante (cliente → agente) | ✅ | ✅ | — | — | ✅ |
| Saliente (agente → cliente) | ✅ | ✅ | — | — | ✅ |


## Qué se Despliega

| Recurso | Servicio | Propósito |
|---|---|---|
| Endpoint `/messages` (GET & POST) | API Gateway | Recibe verificación de webhook de Meta y mensajes entrantes |
| Inbound Handler | Lambda | Procesa mensajes de Messenger y los enruta a Amazon Connect Chat |
| Outbound Handler | Lambda | Envía respuestas de agentes de vuelta a Messenger vía Send API |
| Tabla Active Connections | DynamoDB | Rastrea sesiones de chat abiertas (`contactId` PK, `userId` GSI) |
| Tabla Messenger Users | DynamoDB | Cachea perfiles de usuario de Messenger (expiración por TTL) |
| Topic `messages_out` | SNS | Entrega eventos de streaming de Amazon Connect al Outbound Handler |
| `messenger-page-token` | Secrets Manager | Almacena el Facebook Page Access Token |
| `/meta/messenger/config` | SSM Parameter Store | Contiene instance ID de Connect, contact flow ID, token de verificación |
| `/meta/messenger/webhook/url` | SSM Parameter Store | Almacena la URL del callback de API Gateway desplegado |

## Estimación de Costos

Escenario de ejemplo: 1,000 conversaciones por mes, promediando 10 mensajes cada una (5 entrantes + 5 salientes), totalizando 10,000 mensajes.

| Componente | Costo Mensual Estimado | Notas |
|---|---|---|
| Infraestructura (API GW, Lambda, DynamoDB, SNS, Secrets Manager) | ~$0.71 | Despreciable a esta escala |
| Amazon Connect Chat (Entrante) | $20.00 | 5,000 msgs × $0.004/msg |
| Amazon Connect Chat (Saliente) | $20.00 | 5,000 msgs × $0.004/msg |
| **Total** | **~$40.71** | |

El costo de infraestructura es mínimo — la mensajería de Amazon Connect Chat es el principal generador de costos a $0.004 por mensaje en cada dirección. Consulta los [precios de Amazon Connect](https://aws.amazon.com/connect/pricing/) para tarifas actuales.

Para reducir costos de Connect Chat en conversaciones de alto volumen, considera agregar una [capa de buffering de mensajes](https://github.com/aws-samples/sample-whatsapp-end-user-messaging-connect-chat/tree/main/whatsapp-eum-connect-chat) para agregar mensajes consecutivos rápidos.

## Prerrequisitos de Despliegue

Antes de comenzar necesitarás:

### Página de Facebook y Meta App

Necesitas una Página de Facebook y una Meta App configurada con la Messenger Platform. Los pasos principales son:

1. Tener o crear una Meta Business Account
2. Crear una Meta App y agregar el producto Messenger
3. Conectar tu Página de Facebook y generar un Page Access Token
4. Generar un Page Access Token que no expire (los tokens de corta duración expiran en ~1-2 horas)

Consulta la [Guía de Configuración de Facebook](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/facebook_setup.md) para instrucciones detalladas paso a paso, incluyendo el flujo de intercambio de tokens para obtener un token que no expire.

⚠️ Importante: En modo desarrollo, tu app solo puede recibir mensajes de cuentas de Facebook con un rol en la Meta App (Admin, Developer, Tester). Para uso en producción, necesitas App Review con Advanced Access para `pages_messaging`.

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
cd sample-amazon-connect-social-integration/facebook-messenger-connect-chat
```

### 2. Despliega con CDK

Sigue las instrucciones en la [Guía de Despliegue CDK](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/general_cdk_deploy.md) para configuración del entorno y comandos de despliegue.

## Configuración Post-despliegue

### Paso 1: Actualizar el Page Access Token en Secrets Manager

El stack crea un secreto en Secrets Manager llamado [`messenger-page-token`](https://console.aws.amazon.com/secretsmanager/secret?name=messenger-page-token) con un valor placeholder. Actualízalo con tu Page Access Token real que no expire.

Consulta [Guía de Configuración de Facebook — Paso 5](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/facebook_setup.md#step-5-generate-a-long-lived-page-access-token) para saber cómo generar un token que no expire.

### Paso 2: Actualizar el Parámetro de Configuración SSM

Después del despliegue, ve a [AWS Systems Manager - Parameter Store](https://console.aws.amazon.com/systems-manager/parameters) y actualiza el parámetro SSM `/meta/messenger/config` con los detalles de Amazon Connect y Facebook:

| Parámetro | Descripción |
|---|---|
| `instance_id` | Tu Amazon Connect Instance ID |
| `contact_flow_id` | El ID del Inbound Contact Flow para chat |
| `MESSENGER_VERIFICATION_TOKEN` | Un string secreto que tú eliges — debe coincidir con lo que ingreses en la configuración del webhook de Meta |

### Paso 3: Configurar el Webhook en el Meta App Dashboard

1. Ve a tu Meta App Dashboard → Messenger → Settings → Webhooks
2. Configura la **Callback URL** con la URL de API Gateway. La puedes encontrar en el parámetro SSM `/meta/messenger/webhook/url` en [AWS Systems Manager - Parameter Store](https://console.aws.amazon.com/systems-manager/parameters)
3. Configura el **Verify Token** con el mismo valor que usaste para `MESSENGER_VERIFICATION_TOKEN` arriba
4. Suscríbete al campo de webhook `messages` (como mínimo)
5. Suscribe tu Página a la app para que reciba eventos webhook

Para más detalles, consulta [Guía de Configuración de Facebook — Paso 4](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/facebook_setup.md#step-4-configure-webhooks).

## Pruebas

Ve a tu instancia de Amazon Connect y [abre el Contact Control Panel (CCP)](https://docs.aws.amazon.com/connect/latest/adminguide/launch-ccp.html).

<div align="center">
<video src="https://github.com/user-attachments/assets/27ff5980-91cc-4db6-8c4b-88e82cd0def0" width="540" controls></video>
</div>

Prueba estos escenarios:

- Envía un mensaje a tu Página de Facebook desde otra cuenta de Facebook — debería aparecer como un nuevo contacto de chat en el CCP
- Responde desde el CCP — la respuesta debería llegar al chat de Messenger del cliente
- Envía una imagen desde Messenger — debería aparecer como un adjunto de imagen en el chat del agente
- Envía un archivo (PDF, documento) desde Messenger — debería aparecer como un adjunto de archivo
- Desde el lado del agente, envía una imagen o documento — debería aparecer en el chat de Messenger del cliente

## Consideraciones Importantes sobre Facebook Messenger

### Ventana de Mensajería de 24 Horas

Facebook Messenger tiene una **ventana de mensajería estándar de 24 horas**:
- Después de que un usuario envía un mensaje, tu Página tiene 24 horas para responder
- Fuera de esta ventana, solo puedes enviar mensajes usando [Message Tags](https://developers.facebook.com/docs/messenger-platform/send-messages/message-tags) (casos de uso limitados)
- Cada nuevo mensaje del usuario reabre la ventana de 24 horas

### Límites de Tasa

- Messenger Platform tiene límites de tasa basados en el nivel de uso de tu app
- Monitorea los headers de respuesta del API para información de límites de tasa
- Implementa backoff exponencial para reintentos

### App Review

- En **modo desarrollo**, tu app solo puede recibir mensajes de cuentas con un rol en la app (Admin, Developer, Tester)
- Para uso en producción con clientes reales, necesitas enviar para [App Review](https://developers.facebook.com/docs/app-review) y solicitar **Advanced Access** para `pages_messaging`

### Seguridad del Page Access Token

- El Page Access Token otorga acceso completo de mensajería a tu Página — trátalo como una contraseña
- Almacénalo en AWS Secrets Manager (como hace esta solución), nunca en código o variables de entorno
- Usa el flujo de token que no expire descrito en la [Guía de Configuración de Facebook](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/facebook_setup.md) para evitar problemas de rotación de tokens

## Próximos Pasos

Esta solución maneja el flujo principal de mensajería Messenger-a-Connect. Algunas ideas para extenderla:

- Usar Amazon Bedrock para analizar imágenes entrantes y dar contexto a los agentes
- Usar [Amazon Connect AI Agents](https://docs.aws.amazon.com/connect/latest/adminguide/agentic-self-service.html) para autoservicio agéntico, permitiendo a los clientes resolver problemas comunes sin esperar a un agente humano
- Combinar con la [integración de Instagram DM](https://github.com/aws-samples/sample-amazon-connect-social-integration/tree/main/instagram-dm-connect-chat) para manejar ambos canales de Meta desde una sola instancia de Amazon Connect

### Aprovechar Amazon Connect Customer Profiles

Esta solución ya obtiene datos del perfil de Messenger (nombre, apellido, foto de perfil) y los pasa como atributos de contacto. Puedes ir más allá integrando con [Amazon Connect Customer Profiles](https://docs.aws.amazon.com/connect/latest/adminguide/customer-profiles.html) para dar a los agentes una vista unificada del cliente a través de canales. Luego en tu Contact Flow, usa el [bloque Customer Profiles](https://docs.aws.amazon.com/connect/latest/adminguide/customer-profiles-block.html) para recuperar el perfil y mostrarlo en el workspace del agente. El agente ve el nombre del cliente, historial de interacciones previas y datos de otros canales — todo antes de escribir una respuesta.

## Recursos

- [Repositorio del Proyecto](https://github.com/aws-samples/sample-amazon-connect-social-integration)
- [Guía de Administrador de Amazon Connect](https://docs.aws.amazon.com/connect/latest/adminguide/what-is-amazon-connect.html)
- [Guía de Configuración de Facebook](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/facebook_setup.md)
