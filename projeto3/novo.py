"""
Script para rodar no editor Python do QGIS.

Fluxo:
1. Baixa um GeoJSON publico.
2. Importa o dado para um banco PostGIS.
3. Executa uma consulta SQL que retorna geometria.
4. Carrega o resultado no QGIS.
"""

from pathlib import Path
from tempfile import gettempdir
from urllib.request import urlretrieve

from osgeo import ogr
from qgis.PyQt.QtWidgets import QInputDialog, QLineEdit, QMessageBox
from qgis.core import QgsDataSourceUri, QgsProject, QgsVectorLayer
from qgis.utils import iface


DATA_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_admin_0_countries.geojson"
)
SCHEMA = "public"
TABLE_NAME = "p3_countries"
QUERY_LAYER_NAME = "p3_america_do_sul"
VIEW_NAME = "p3_america_do_sul_view"


class PostGISManager:
    """Concentra a logica de importacao e criacao da camada SQL."""

    def __init__(self, host, port, database, user, password, schema=SCHEMA):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.schema = schema

    def ogr_connection_string(self):
        return (
            f"PG:host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )

    def import_geojson(self, geojson_path, table_name=TABLE_NAME):
        source_ds = ogr.Open(str(geojson_path))
        if source_ds is None:
            raise RuntimeError(f"Nao foi possivel abrir o arquivo {geojson_path}.")

        source_layer = source_ds.GetLayer(0)
        if source_layer is None:
            raise RuntimeError("Nao foi possivel obter a camada do GeoJSON.")

        target_ds = ogr.Open(self.ogr_connection_string(), update=1)
        if target_ds is None:
            raise RuntimeError("Nao foi possivel conectar ao PostGIS via OGR.")

        target_ds.ExecuteSQL(
            f'DROP TABLE IF EXISTS "{self.schema}"."{table_name}" CASCADE'
        )

        options = [
            f"SCHEMA={self.schema}",
            "OVERWRITE=YES",
            "GEOMETRY_NAME=geom",
            "FID=ogc_fid",
            "PRECISION=NO",
        ]
        imported_layer = target_ds.CopyLayer(source_layer, table_name, options)
        if imported_layer is None:
            raise RuntimeError("Falha ao importar a camada para o PostGIS.")

        source_ds = None
        target_ds = None

    def execute_sql(self, sql):
        target_ds = ogr.Open(self.ogr_connection_string(), update=1)
        if target_ds is None:
            raise RuntimeError("Nao foi possivel conectar ao PostGIS via OGR.")

        result = target_ds.ExecuteSQL(sql)
        if result is not None:
            target_ds.ReleaseResultSet(result)
        target_ds = None

    def create_query_view(
        self,
        table_name=TABLE_NAME,
        view_name=VIEW_NAME,
        schema=SCHEMA,
    ):
        self.execute_sql(f'DROP VIEW IF EXISTS "{schema}"."{view_name}" CASCADE')
        self.execute_sql(
            f"""
            CREATE VIEW "{schema}"."{view_name}" AS
            SELECT
                ogc_fid,
                admin,
                continent,
                geom
            FROM "{schema}"."{table_name}"
            WHERE continent = 'South America'
            """
        )

    def qgis_uri(self):
        uri = QgsDataSourceUri()
        uri.setConnection(
            self.host,
            str(self.port),
            self.database,
            self.user,
            self.password,
        )
        return uri


def ask_text(title, label, default="", password=False):
    echo_mode = QLineEdit.Password if password else QLineEdit.Normal
    value, accepted = QInputDialog.getText(
        iface.mainWindow(),
        title,
        label,
        echo_mode,
        default,
    )
    if not accepted or not value.strip():
        raise RuntimeError(f"Entrada cancelada: {label}")
    return value.strip()


def ask_connection_parameters():
    return {
        "host": ask_text("PostGIS", "Host:", "localhost"),
        "port": ask_text("PostGIS", "Porta:", "5432"),
        "database": ask_text("PostGIS", "Banco de dados:"),
        "user": ask_text("PostGIS", "Usuario:"),
        "password": ask_text("PostGIS", "Senha:", password=True),
    }


def download_vector_data(url=DATA_URL):
    target_dir = Path(gettempdir()) / "projeto3_qgis_postgis"
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / "countries.geojson"
    urlretrieve(url, target_path)

    if not target_path.exists():
        raise RuntimeError("O download do dado vetorial falhou.")

    return target_path


def load_query_layer(connection, schema=SCHEMA, view_name=VIEW_NAME):
    uri = connection.qgis_uri()
    uri.setDataSource(schema, view_name, "geom", "", "ogc_fid")
    uri.setSrid("4326")
    uri.setUseEstimatedMetadata(True)

    layer = QgsVectorLayer(uri.uri(False), QUERY_LAYER_NAME, "postgres")
    if not layer.isValid():
        raise RuntimeError("A camada SQL retornada pelo PostGIS nao e valida.")

    QgsProject.instance().addMapLayer(layer)
    return layer


def run():
    try:
        params = ask_connection_parameters()
        connection = PostGISManager(**params)

        print("Baixando dado vetorial...")
        geojson_path = download_vector_data()
        print(f"Arquivo salvo em: {geojson_path}")

        print("Importando dado para o PostGIS...")
        connection.import_geojson(geojson_path)
        print(f'Tabela criada: {SCHEMA}.{TABLE_NAME}')

        print("Executando consulta SQL no PostGIS...")
        connection.create_query_view()
        print(f'View criada: {SCHEMA}.{VIEW_NAME}')

        print("Carregando consulta SQL no QGIS...")
        layer = load_query_layer(connection)
        print(f'Camada adicionada ao QGIS: {layer.name()}')

        QMessageBox.information(
            iface.mainWindow(),
            "Projeto 3",
            (
                "Fluxo concluido com sucesso.\n\n"
                f"Tabela PostGIS: {SCHEMA}.{TABLE_NAME}\n"
                f"View SQL: {SCHEMA}.{VIEW_NAME}\n"
                f"Camada no QGIS: {QUERY_LAYER_NAME}"
            ),
        )
    except Exception as exc:
        QMessageBox.critical(
            iface.mainWindow(),
            "Projeto 3 - erro",
            str(exc),
        )
        print(f"Erro: {exc}")


run()
