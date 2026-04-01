# DMs de Instagram y Amazon Connect Chat

<table>
<tr>
<td width="50%">

_Aprende cómo conectar los Mensajes Directos de Instagram con Amazon Connect Chat para una atención al cliente fluida. Esta guía paso a paso cubre la arquitectura completa usando AWS CDK, AWS Lambda, Amazon API Gateway, Amazon DynamoDB y Amazon Connect. Desde recibir DMs de clientes hasta enrutarlos a agentes, reenviar respuestas de agentes a Instagram y manejar archivos adjuntos en ambas direcciones — todo con gestión automática de sesiones y caché de perfiles de usuario._

</td>
<td width="50%">

![Demo](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/instagram-dm-connect-chat/demo_instagram_connect_chat.gif)

</td>
</tr>
</table>


Tus clientes ya están en Instagram. Navegan tus productos, revisan tus stories, y cuando tienen una pregunta — envían un DM. Si tu equipo de soporte tiene que alternar entre Instagram y su herramienta de contact center, estás perdiendo tiempo y contexto.

En este blog, aprenderás cómo conectar los Mensajes Directos de Instagram directamente a Amazon Connect Chat, para que tus agentes manejen conversaciones de Instagram desde el mismo workspace que usan para todos los demás canales. Sin cambiar de app, sin copiar y pegar, sin mensajes perdidos.

Revisa el código en [Github](https://github.com/aws-samples/sample-amazon-connect-social-integration)


## Qué vas a construir

Un puente de mensajería bidireccional entre DMs de Instagram y Amazon Connect que:

1. Recibe DMs entrantes de Instagram vía webhooks de Meta y los enruta a Amazon Connect Chat
2. Reenvía las respuestas de los agentes desde Amazon Connect de vuelta a Instagram a través del Graph API
3. Gestiona sesiones de chat automáticamente — creando nuevas, reutilizando activas y limpiando las expiradas
4. Cachea perfiles de usuario de Instagram (nombre, username, foto de perfil, cantidad de seguidores) en DynamoDB para reducir llamadas al API
5. Maneja archivos adjuntos en ambas direcciones — imágenes de clientes, e imágenes y documentos de agentes

El resultado final: los agentes ven las conversaciones de Instagram como contactos de chat regulares en su workspace de Amazon Connect, con el nombre y la información de perfil del cliente.

## Arquitectura

![Diagrama de Arquitectura](https://raw.githubusercontent.com/aws-samples/sample-amazon-connect-social-integration/main/instagram-dm-connect-chat/instagram-connect-chat.svg)

Así funciona el flujo:

1. Un cliente envía un DM en Instagram. Meta entrega el evento webhook a un endpoint de API Gateway
2. La Lambda del Inbound Handler valida el webhook, parsea el mensaje y busca o crea una sesión de Amazon Connect Chat
3. El perfil de Instagram del cliente se obtiene vía Graph API y se cachea en DynamoDB
4. Los mensajes de texto y archivos adjuntos se envían a la sesión de Connect Chat vía el Participant API
5. Cuando un agente responde, Amazon Connect publica el evento a un topic SNS vía contact streaming
6. La Lambda del Outbound Handler recibe el evento SNS, busca el ID de Instagram del cliente y envía la respuesta a través del Instagram Graph API

## Entrante: Instagram → Amazon Connect

Cuando un cliente envía un DM a tu cuenta Business de Instagram, el flujo entrante maneja todo, desde la validación del webhook hasta la entrega del mensaje.

### 1. Validación del Webhook y Parseo de Mensajes

Meta envía eventos webhook a tu endpoint `/messages` de API Gateway. La Lambda primero maneja las solicitudes GET para verificación del webhook — Meta envía un token de desafío que debe ser devuelto con el token de verificación correcto.

Para solicitudes POST (mensajes reales), la clase `InstagramService` parsea el payload del webhook. Los webhooks de Instagram llegan con `object: "instagram"` y contienen entries con datos de mensajería:

```python
class InstagramMessage:
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

El servicio también filtra mensajes echo — mensajes enviados por tu propia cuenta de Instagram — para prevenir loops infinitos.

### 2. Obtención y Caché de Perfiles de Usuario

Antes de enrutar el mensaje a Connect, el handler obtiene el perfil de Instagram del remitente usando el Graph API. Esto le da al agente contexto sobre con quién está hablando:

```python
def get_user_profile(self, instagram_scoped_id, fields=None):
    # Verificar caché en memoria primero
    if instagram_scoped_id in self.user_profiles:
        return self.user_profiles[instagram_scoped_id]

    # Verificar tabla de usuarios en DynamoDB
    if USERS_TABLE_NAME:
        users_table = TableService(table_name=USERS_TABLE_NAME)
        db_profile = users_table.get_item({"id": instagram_scoped_id})
        if db_profile:
            return db_profile

    # Obtener del Graph API como último recurso
    params = {'fields': ','.join(fields), 'access_token': self.access_token}
    url = f"https://graph.instagram.com/v24.0/{instagram_scoped_id}?{urlencode(params)}"
    # ... obtener y cachear
```

El perfil incluye campos como `name`, `username`, `profile_pic`, `follower_count`, `is_user_follow_business` e `is_verified_user`. Los perfiles se cachean en una tabla DynamoDB con un TTL de 7 días, así que las conversaciones repetidas se saltan la llamada al API.

### 3. Gestión de Sesiones

El handler verifica en DynamoDB si existe una sesión de chat activa usando el Instagram-scoped ID del remitente:

- Si existe una sesión, envía el mensaje usando el `connectionToken` almacenado. Si el token expiró (AccessDeniedException), crea automáticamente una nueva sesión.
- Si no existe sesión, llama a `StartChatContact` para crear un nuevo Amazon Connect Chat, inicia contact streaming al topic SNS, crea una conexión de participante y almacena todo en DynamoDB.


### 4. Manejo de Archivos Adjuntos (Entrante)

Cuando un cliente envía una imagen, el handler la descarga del CDN de Instagram y la sube a la sesión de Connect Chat usando el flujo de tres pasos del Participant API:

1. `start_attachment_upload` — crea un slot de carga con una URL pre-firmada
2. `PUT` a la URL pre-firmada — sube el contenido binario
3. `complete_attachment_upload` — finaliza la carga

Si la descarga o carga falla, el handler envía la URL del adjunto como mensaje de texto para que el agente aún tenga acceso al contenido.

## Saliente: Amazon Connect → Instagram

Cuando un agente responde desde el workspace de Amazon Connect, el flujo saliente entrega el mensaje de vuelta a Instagram.

### 1. Eventos de Streaming vía SNS

Amazon Connect publica eventos de streaming de chat a un topic SNS. La Lambda del Outbound Handler se suscribe a este topic y procesa tres tipos de eventos:

- `MESSAGE` — mensajes de texto del agente
- `ATTACHMENT` — archivos adjuntos enviados por el agente
- `EVENT` — eventos de unión/salida de participantes y fin de chat

Los mensajes del rol `CUSTOMER` se omiten para evitar loops echo.

### 2. Envío de Mensajes de Texto

Para mensajes de texto con visibilidad `CUSTOMER` o `ALL`, el handler busca el Instagram-scoped ID del cliente y el ID de la cuenta Business de Instagram en DynamoDB, luego envía la respuesta vía el Graph API:

```python
def send_instagram_text(access_token, text_message, recipient_id, instagram_account_id):
    url = f"https://graph.instagram.com/v24.0/{instagram_account_id}/messages"
    
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text_message},
        "access_token": access_token,
    }
    # POST al Instagram Graph API
```

### 3. Envío de Archivos Adjuntos

Cuando un agente envía un archivo desde el widget de Connect Chat, el handler obtiene una URL firmada del adjunto y lo reenvía a Instagram como mensaje multimedia. El tipo MIME determina el tipo de mensaje de Instagram:

| Prefijo MIME | Tipo Instagram |
|---|---|
| `image/*` | `image` |
| `video/*` | `video` |
| `audio/*` | `audio` |
| todo lo demás | `file` |

### 4. Limpieza de Sesiones

Cuando un participante sale o el chat termina, el handler elimina el registro de conexión de DynamoDB para que el próximo mensaje entrante inicie una sesión nueva.

## Tipos de Mensajes Soportados

| Dirección | Texto | Imágenes | Documentos |
|---|---|---|---|
| Entrante (cliente → agente) | ✅ | ✅ | — |
| Saliente (agente → cliente) | ✅ | ✅ | ✅ |

Enviar documentos desde la app de Instagram no es posible actualmente (limitaciones de la app de Instagram), pero los clientes pueden recibir documentos enviados por agentes desde Amazon Connect.

## Qué se Despliega

| Recurso | Servicio | Propósito |
|---|---|---|
| Endpoint `/messages` (GET & POST) | API Gateway | Recibe verificación de webhook de Meta y mensajes entrantes |
| Inbound Handler | Lambda | Procesa mensajes de Instagram y los enruta a Amazon Connect Chat |
| Outbound Handler | Lambda | Envía respuestas de agentes de vuelta a Instagram vía Graph API |
| Tabla Active Connections | DynamoDB | Rastrea sesiones de chat abiertas (`contactId` PK, `userId` GSI) |
| Tabla Instagram Users | DynamoDB | Cachea perfiles de usuario de Instagram (expiración por TTL) |
| Topic `messages_out` | SNS | Entrega eventos de streaming de Amazon Connect al Outbound Handler |
| `instagram-token` | Secrets Manager | Almacena el Instagram User Access Token |
| `/meta/instagram/config` | SSM Parameter Store | Contiene instance ID de Connect, contact flow ID, token de verificación e Instagram account ID |
| `/meta/instagram/webhook/url` | SSM Parameter Store | Almacena la URL del callback de API Gateway desplegado |


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

### Cuenta Business de Instagram y Meta App

Necesitas una cuenta de Instagram Business o Creator conectada a una Meta App con el API de Instagram configurado. Los pasos principales son:

1. Tener o crear una Meta Business Account
2. Crear una Meta App y agregar el producto de Instagram
3. Configurar Instagram Login y generar un Instagram User Access Token
4. Asegurarte de que tu cuenta de Instagram sea Business o Creator (las cuentas personales no soportan el Messaging API)

Consulta la [Guía de Configuración de Instagram](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/instagram_setup.md) para instrucciones detalladas paso a paso.

⚠️ Importante: En modo desarrollo, tu app solo puede recibir mensajes de cuentas de Instagram con un rol en la Meta App.

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
cd sample-amazon-connect-social-integration/instagram-dm-connect-chat
```

### 2. Despliega con CDK

Sigue las instrucciones en la [Guía de Despliegue CDK](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/general_cdk_deploy.md) para configuración del entorno y comandos de despliegue.

## Configuración Post-despliegue

### Paso 1: Actualizar el Instagram Access Token en Secrets Manager

El stack crea un secreto en Secrets Manager llamado [`instagram-token`](https://console.aws.amazon.com/secretsmanager/secret?name=instagram-token) con un valor placeholder. Actualízalo con tu Instagram User Access Token real.

Consulta la [Guía de Configuración de Instagram](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/instagram_setup.md) para saber cómo generar este token.

### Paso 2: Actualizar el Parámetro de Configuración SSM

Después del despliegue, ve a [AWS Systems Manager - Parameter Store](https://console.aws.amazon.com/systems-manager/parameters) y actualiza el parámetro SSM `/meta/instagram/config` con los detalles de Amazon Connect e Instagram:

| Parámetro | Descripción |
|---|---|
| `instance_id` | Tu Amazon Connect Instance ID |
| `contact_flow_id` | El ID del Inbound Contact Flow para chat |
| `INSTAGRAM_VERIFICATION_TOKEN` | Un string secreto que tú eliges — debe coincidir con lo que ingreses en la configuración del webhook de Meta |
| `instagram_account_id` | Tu Instagram Business Account ID (ver nota abajo) |

Para encontrar tu `instagram_account_id`:

- En tu Meta App Dashboard → Instagram → API Setup with Instagram Login → expande "1. Generate access tokens" → el ID está debajo de la cuenta de Instagram vinculada
- O llama al Graph API:

```bash
curl -X GET "https://graph.instagram.com/me?fields=id,username,account_type,user_id&access_token=YOUR_IG_ACCESS_TOKEN"
```

El campo `user_id` en la respuesta es tu `instagram_account_id`.

### Paso 3: Configurar el Webhook en el Meta App Dashboard

1. Ve a tu Meta App Dashboard → Instagram → API Setup with Instagram Login → Webhooks
2. Configura la **Callback URL** con la URL de API Gateway. La puedes encontrar en el parámetro SSM `/meta/instagram/webhook/url`
3. Configura el **Verify Token** con el mismo valor que usaste para `INSTAGRAM_VERIFICATION_TOKEN` arriba
4. Suscríbete al campo de webhook `messages`

Para más detalles, consulta la [Guía de Configuración de Instagram](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/instagram_setup.md).

## Pruebas

Ve a tu instancia de Amazon Connect y [abre el Contact Control Panel (CCP)](https://docs.aws.amazon.com/connect/latest/adminguide/launch-ccp.html).

<div align="center">
<video src="https://github.com/user-attachments/assets/5f6d988b-5340-4b32-ac1b-ec85114adb2b" width="540" controls></video>
</div>

Prueba estos escenarios:

- Envía un DM a tu cuenta Business de Instagram desde otra cuenta de Instagram — debería aparecer como un nuevo contacto de chat en el CCP
- Responde desde el CCP — la respuesta debería llegar a los DMs de Instagram del cliente
- Envía una imagen desde Instagram — debería aparecer como un adjunto de imagen en el chat del agente
- Desde el lado del agente, envía una imagen o documento — debería aparecer en los DMs de Instagram del cliente


## Consideraciones Importantes sobre Instagram

### Ventana de Mensajería de 24 Horas

Instagram tiene una **ventana de mensajería estándar de 24 horas**:
- Después de que un usuario envía un mensaje, tu cuenta tiene 24 horas para responder
- Fuera de esta ventana, la mensajería está restringida
- Cada nuevo mensaje del usuario reabre la ventana de 24 horas

### Ventana de Agente Humano

Instagram proporciona una **ventana de agente humano de 7 días** para conversaciones que son escaladas a un agente humano. Esta ventana extendida permite a los agentes más tiempo para resolver problemas complejos.

### App Review

- En **modo desarrollo**, tu app solo puede recibir mensajes de cuentas de Instagram con un rol en la Meta App (Admin, Developer, Tester)
- Para uso en producción con clientes reales, necesitas enviar para [App Review](https://developers.facebook.com/docs/app-review) y solicitar los permisos requeridos

### Límites de Tasa

- El Instagram Messaging API tiene límites de tasa basados en el nivel de uso de tu app
- Monitorea los headers de respuesta del API para información de límites de tasa

## Próximos Pasos

Esta solución maneja el flujo principal de mensajería Instagram-a-Connect. Algunas ideas para extenderla:

- Agregar soporte para menciones y respuestas de Instagram Stories
- Usar Amazon Bedrock para analizar imágenes entrantes y dar contexto a los agentes antes de que respondan
- Usar [Amazon Connect AI Agents](https://docs.aws.amazon.com/connect/latest/adminguide/agentic-self-service.html) para autoservicio agéntico, permitiendo a los clientes resolver problemas comunes sin esperar a un agente humano
- Combinar con la [integración de Facebook Messenger](https://github.com/aws-samples/sample-amazon-connect-social-integration/tree/main/facebook-messenger-connect-chat) para manejar ambos canales de Meta desde una sola instancia de Amazon Connect

### Aprovechar Amazon Connect Customer Profiles

Esta solución ya obtiene datos del perfil de Instagram (nombre, username, foto de perfil, cantidad de seguidores) y los pasa como atributos de contacto. Puedes ir más allá integrando con [Amazon Connect Customer Profiles](https://docs.aws.amazon.com/connect/latest/adminguide/customer-profiles.html) para dar a los agentes una vista unificada del cliente a través de canales. Luego en tu Contact Flow, usa el [bloque Customer Profiles](https://docs.aws.amazon.com/connect/latest/adminguide/customer-profiles-block.html) para recuperar el perfil y mostrarlo en el workspace del agente. El agente ve el nombre del cliente, su handle de Instagram, cantidad de seguidores y cualquier historial de interacciones previas — todo antes de escribir una respuesta.

## Recursos

- [Repositorio del Proyecto](https://github.com/aws-samples/sample-amazon-connect-social-integration)
- [Guía de Administrador de Amazon Connect](https://docs.aws.amazon.com/connect/latest/adminguide/what-is-amazon-connect.html)
- [Instagram Messaging API — Overview](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api)
- [Instagram Graph API — User Profile](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/api-reference)
- [Meta Webhooks — Getting Started](https://developers.facebook.com/docs/graph-api/webhooks/getting-started)
- [Guía de Configuración de Instagram](https://github.com/aws-samples/sample-amazon-connect-social-integration/blob/main/instagram_setup.md)
