# Football Data Explorer
Link al dataset: https://www.kaggle.com/datasets/davidcariboo/player-scores 
Aplicacion Streamlit que consulta las tablas del dataset `football_data` en Google BigQuery y muestra tres graficos interactivos.

## Tablas utilizadas

- `clubs`: top de clubes por valor de mercado.
- `players` y `player_valuations`: evolucion del valor de un jugador.
- `game_events`: cantidad de eventos por tipo.

## Ejecutar localmente

1. Instalar dependencias:

   ```powershell
   pip install -r requirements.txt
   ```

2. Autenticarse con Google Cloud:

   ```powershell
   gcloud auth application-default login
   ```

3. Ejecutar la app:

   ```powershell
   streamlit run app.py
   ```

La cuenta debe tener permisos para consultar el proyecto y el dataset `football_data`.

## Publicar en Streamlit Community Cloud

Sube `app.py` y `requirements.txt` a GitHub y selecciona `app.py` como archivo principal. En `Settings > Secrets`, agrega el proyecto:

```toml
gcp_project = "tu-project-id"
```

Para la autenticacion en la nube, agrega tambien las credenciales de una cuenta de servicio en los secrets de Streamlit. El bloque debe tener las mismas claves del JSON descargado desde Google Cloud:

```toml
[gcp_service_account]
type = "service_account"
project_id = "tu-project-id"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

No subas el archivo JSON de credenciales al repositorio.
