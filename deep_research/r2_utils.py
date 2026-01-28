import os
import boto3
from botocore.config import Config
from .config import (
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_ENDPOINT_URL,
    R2_BUCKET_NAME,
)
from .logger import logger


class R2Manager:
    """
    Gestiona la subida de archivos a Cloudflare R2 (bucket privado)
    y devuelve una URL firmada temporal.
    """

    def __init__(self):
        self.bucket_name = R2_BUCKET_NAME
        self._s3_client = None

    @property
    def s3_client(self):
        if self._s3_client is None:
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=R2_ENDPOINT_URL,
                aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                config=Config(signature_version="s3v4"),
                region_name="auto",
            )
        return self._s3_client

    def upload_file(self, file_path: str, object_name: str = None, expires_in: int = 180) -> str:
        """
        Sube un archivo a R2 y devuelve una URL firmada temporal (por defecto 3 min).

        Args:
            file_path: Ruta local del archivo
            object_name: Nombre del objeto en R2 (si es None se usa el nombre del archivo)
            expires_in: Segundos de validez de la URL firmada (180 = 3 min)

        Returns:
            URL firmada temporal para descargar el archivo
        """
        if object_name is None:
            object_name = os.path.basename(file_path)

        try:
            logger.log_info(
                f"Subiendo {file_path} a R2 bucket {self.bucket_name} como {object_name}..."
            )

            # Subir archivo (privado)
            self.s3_client.upload_file(file_path, self.bucket_name, object_name)

            # URL firmada temporal (descarga)
            signed_url = self.s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.bucket_name, "Key": object_name},
                ExpiresIn=expires_in,
            )

            logger.log_success(
                f"Archivo subido. URL temporal (expira en {expires_in}s): {signed_url}"
            )
            return signed_url

        except Exception as e:
            logger.log_error(f"Error subiendo archivo a R2: {e}")
            raise


r2_manager = R2Manager()
