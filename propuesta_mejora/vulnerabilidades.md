# Análisis de vulnerabilidades — Tapo Dashboard

> Fecha del análisis: 2026-04-23

---

## 🔴 Críticas

### 1. `pickle` en base de datos de personas
**Archivo:** `backend/recognizer.py:244,255`

Los embeddings faciales se serializan con `pickle.dumps/loads` y se almacenan en SQLite. Si alguien puede escribir en `data/persons.db`, puede inyectar un payload pickle que ejecute código arbitrario al cargar.

**Vector:** acceso físico al archivo o escritura vía path traversal.

**Fix:** serializar con `numpy.save` a bytes o JSON en lugar de pickle.

---

### 2. Sin validación de tipo/tamaño en upload de imagen
**Archivo:** `backend/main.py:327`

`POST /api/enroll_face` acepta cualquier `UploadFile` sin verificar `content_type` ni tamaño. Un atacante puede subir archivos de cientos de MB o payloads no-imagen.

**Fix:** validar `content_type in {"image/jpeg", "image/png"}` y limitar a ~10 MB.

---

## 🟠 Altas

### 3. Sin CORS configurado
No hay `CORSMiddleware`. En HTTP cualquier web puede hacer requests cross-origin a la API desde el navegador de un usuario de la LAN.

**Fix:** añadir `CORSMiddleware` con `allow_origins=["https://<tu-IP>:8000"]`.

---

### 4. Credenciales de cámara en texto plano en `CAMERA_URL`
`CAMERA_URL` contiene usuario y contraseña embebidos en la URL RTSP: `rtsp://user:pass@IP/...`.

**Fix:** construir la URL RTSP dinámicamente desde `TAPO_USER`/`TAPO_PASS`, nunca con credenciales embebidas en la URL.

---

### 5. WS tokens sin TTL
**Archivo:** `backend/auth.py`

Los tokens de WebSocket se acumulan en memoria indefinidamente. Un token emitido pero no usado nunca expira.

**Fix:** almacenar `(token, issued_at)` y purgar tokens con más de 60 segundos.

---

### 6. `YOLO_MODEL_PATH` sin validación
**Archivo:** `backend/config.py`

`YOLO_MODEL_PATH` se pasa directamente a `YOLO(model_path)`. Si el `.env` apunta a un archivo malicioso (pickle en `.pt`), Ultralytics lo cargaría.

**Fix:** validar que la extensión sea `.pt` y que el path no escape del directorio del proyecto.

---

## 🟡 Medias

### 7. Sin rate limiting en ningún endpoint
`/api/enroll_face`, `/api/ws-token` y todos los endpoints son llamables sin límite desde la LAN. Posible fuerza bruta o DoS.

**Fix:** `slowapi` (rate limiter para FastAPI) con límite por IP.

---

### 8. Certificado autofirmado sin SAN para la IP local
**Archivo:** `backend/ssl_utils.py`

El cert se genera con SAN solo para `localhost` y `127.0.0.1`, no para la IP LAN (`192.168.1.X`). Los navegadores modernos muestran warning aunque se acepte la excepción.

**Fix:** leer la IP del host y añadirla como SAN al generar el certificado.

---

### 9. Sin headers de seguridad HTTP
Faltan: `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, `Strict-Transport-Security`.

**Fix:** middleware que inyecte estos headers en todas las respuestas.

---

### 10. `limit` en `/api/events` sin cota máxima
**Archivo:** `backend/main.py`

`GET /api/events?limit=9999999` hace una query masiva a SQLite sin límite superior.

**Fix:** `limit: int = Query(default=50, le=500)`.

---

### 11. Sin validación de longitud en `name` de enrolamiento
**Archivo:** `backend/main.py:327`

`name.strip()` no limita la longitud. Nombres de más de 10.000 caracteres llegan a la base de datos.

**Fix:** `name: str = Form(..., max_length=100)`.

---

## 🟢 Bajas

### 12. Logs con URL RTSP incluyendo credenciales
**Archivo:** `backend/main.py`

`logger.info("RTSP stream started: %s", settings.camera_url)` loguea la URL con usuario y contraseña en texto plano.

**Fix:** enmascarar credenciales antes de loguear: `rtsp://***:***@IP/stream`.

---

### 13. Clave privada SSL sin restricción de permisos
**Archivo:** `certs/key.pem`

La clave privada SSL se genera sin restricciones de permisos en Windows.

**Fix:** aplicar permisos 600 tras generación (solo lectura por el propietario).

---

### 14. Sin Subresource Integrity en CDN de Chart.js
**Archivo:** `frontend/index.html`

El `<script>` de Chart.js carga desde CDN externo sin atributo `integrity`. Un CDN comprometido podría servir JavaScript malicioso.

**Fix:** añadir `integrity="sha384-..."` al tag `<script>` de Chart.js.

---

## Resumen de prioridades

| Prioridad | Vulnerabilidad |
|-----------|----------------|
| 🔴 Inmediata | Reemplazar `pickle` con serialización segura |
| 🔴 Inmediata | Validar tipo y tamaño de imagen en upload |
| 🟠 Alta | Añadir CORS restrictivo |
| 🟠 Alta | Separar credenciales RTSP de la URL |
| 🟠 Alta | TTL en tokens WebSocket |
| 🟠 Alta | Validar `YOLO_MODEL_PATH` |
| 🟡 Media | Rate limiting con `slowapi` |
| 🟡 Media | Headers de seguridad HTTP |
| 🟡 Media | SAN con IP LAN en el certificado |
| 🟡 Media | Cota máxima en parámetro `limit` |
| 🟡 Media | Longitud máxima en `name` de enrolamiento |
| 🟢 Baja | Enmascarar credenciales en logs |
| 🟢 Baja | Permisos 600 en `key.pem` |
| 🟢 Baja | Subresource Integrity en Chart.js CDN |
