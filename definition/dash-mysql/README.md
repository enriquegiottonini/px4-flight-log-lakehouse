# Dash + MySQL con Docker

Ejemplo local con dos contenedores y datos agrícolas ficticios.
Requiere Docker Engine con Compose v2 o Docker Desktop iniciado
(en Windows, modo de contenedores Linux).

## 1. Preparación

Extrae el ZIP y abre una terminal en la carpeta dash-mysql, donde está compose.yaml.

Comprueba:

```bash
docker --version
docker compose version
```

Crea .env a partir de .env.example:

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Linux / macOS:

```bash
cp .env.example .env
```

El archivo contiene claves para la demostración local. Puedes editarlas antes
del primer inicio. No publiques .env. Dash usa dash_user, no root.

## 2. Descargar imágenes y arrancar

```bash
docker pull mysql:8.4
docker pull python:3.12-slim
docker compose up -d --build
docker compose ps
```

Compose construye la imagen dash-agricultura:local instalando las librerías de
requirements.txt sobre Python. Los pull son explícitos para fines didácticos:
Compose también puede descargar las imágenes necesarias al construir/arrancar.
La primera ejecución necesita Internet y puede tardar unos minutos.

Abre http://localhost:8050

El desplegable permite elegir temperatura, humedad, radiación o precipitación.
La aplicación consulta MySQL cada 10 segundos. No genera nuevas mediciones;
para observar cambios debes insertar datos.

## 3. Insertar una medición y comprobar el cambio

```bash
docker compose exec mysql mysql -u dash_user -p agricultura
```

Introduce el valor MYSQL_PASSWORD de .env (por defecto DashDemo2026_local).
En la consola MySQL:

```sql
SELECT * FROM mediciones ORDER BY fecha DESC;

INSERT INTO mediciones
(fecha,tempMin,tempMax,tempAvg,humRelMin,humRelMax,humRelAvg,radSol,prec)
VALUES (NOW(),26,33,29.5,40,65,52.5,420,2);

exit;
```

El dashboard mostrará el registro en la siguiente consulta.

## 4. Comandos útiles

```bash
docker compose logs -f dash
docker compose logs -f mysql
docker compose exec dash sh
docker compose stop
docker compose start
docker compose down
docker compose up -d
```

Ctrl+C termina la visualización de logs sin detener los servicios.
stop detiene; start reanuda; down elimina contenedores/red, pero conserva
el volumen de datos. No uses down -v si quieres conservar la base:
la opción -v elimina también sus datos.

Para editar app.py usa un editor en tu computadora y después:

```bash
docker compose up -d --build dash
```

## 5. Conexión y persistencia

Desde Dash: host=mysql, puerto=3306, base=agricultura, usuario=dash_user.
localhost desde Dash apuntaría al propio contenedor Dash.
Compose crea una red compartida y resuelve el nombre del servicio mysql.
Solo se publica Dash, en 127.0.0.1:8050; MySQL queda accesible en la red interna.

Para usar MySQL Workbench desde tu computadora, agrega al servicio mysql:

```yaml
    ports:
      - "127.0.0.1:3307:3306"
```

Reaplica con docker compose up -d. En Workbench usa 127.0.0.1, puerto 3307,
dash_user y la contraseña de .env. Dash sigue usando mysql:3306.

Los datos se guardan en el volumen mysql_data (con prefijo del proyecto).
mysql/01-init.sql solo se ejecuta cuando el directorio de datos está vacío.
Editar el SQL o las claves de .env después del primer inicio no modifica la
base ni las contraseñas ya creadas: aplica cambios mediante SQL.

La comprobación de salud exige una consulta real a mediciones antes de
arrancar Dash. El dashboard vuelve a intentar la consulta si MySQL falla.
Se muestran como máximo las últimas 1000 mediciones, ordenadas por fecha.
Las fechas del ejemplo usan el reloj del contenedor; no se configuran zonas
horarias ni conversiones. Dependencias limitadas por versión mayor, sin
bloqueo exacto de versiones: dos builds futuros pueden resolver parches distintos.

## 6. Problemas frecuentes

- Puerto 8050 ocupado: cambia el mapeo a 127.0.0.1:8051:8050 y abre localhost:8051.
- Error de conexión a Docker: inicia Docker Desktop o el servicio Docker.
- Error al descargar: comprueba acceso a Docker Hub/PyPI, DNS, proxy y firewall.
- MySQL unhealthy: consulta docker compose logs mysql. En equipos lentos puede
  ser necesario aumentar retries. Si falla el primer up, corrige el problema
  y ejecuta nuevamente docker compose up -d.
- Access denied tras editar .env: el volumen conserva las claves originales.

## Validación del paquete

Se revisaron la sintaxis Python, la estructura YAML y la integridad del ZIP.
No se ejecutaron los contenedores: Docker no está disponible en el entorno
de preparación. Este ejemplo es para uso local y no configura publicación,
HTTPS ni autenticación de usuarios del dashboard.

## Documentación

- https://docs.docker.com/compose/how-tos/networking/
- https://docs.docker.com/compose/how-tos/startup-order/
- https://hub.docker.com/_/mysql
- https://dash.plotly.com/
