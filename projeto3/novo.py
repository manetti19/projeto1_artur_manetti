"""
Script para rodar no editor Python do QGIS.

Fluxo:
1. Baixa um GeoJSON publico.
2. Importa o dado para um banco PostGIS.
3. Executa uma consulta SQL que retorna geometria.
4. Carrega o resultado no QGIS.
"""

from pathlib import Path
# Cria caminhos de arquivo de forma segura.
from tempfile import gettempdir
# Fornece uma pasta temporaria do sistema.
from urllib.request import urlretrieve
# Baixa o arquivo vetorial pela URL.

from osgeo import ogr
# Usa o OGR para importar dados e executar SQL no PostGIS.
from qgis.PyQt.QtWidgets import QInputDialog, QLineEdit, QMessageBox
# Cria janelas de entrada e mensagens no QGIS.
from qgis.core import QgsDataSourceUri, QgsProject, QgsVectorLayer
# Cria a conexao, a camada e adiciona no projeto QGIS.
from qgis.utils import iface
# Acessa a interface principal aberta do QGIS.


############    1.    URL do dado vetorial que sera baixado.
DATA_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_admin_0_countries.geojson"
)
# Schema padrao usado no PostGIS.
SCHEMA = "public"
# Nome da tabela que recebera o GeoJSON importado.
TABLE_NAME = "p3_countries"
# Nome da camada exibida no QGIS.
QUERY_LAYER_NAME = "p3_america_do_sul"
# Nome da view criada a partir da consulta SQL.
VIEW_NAME = "p3_america_do_sul_view"


# Classe que concentra as operacoes de banco PostGIS.
class PostGISManager:
    """Concentra a logica de importacao e criacao da camada SQL."""

    # Guarda os parametros de conexao informados pelo usuario.
    def __init__(self, host, port, database, user, password, schema=SCHEMA):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.schema = schema

    # Monta a string de conexao usada pelo OGR.
    def ogr_connection_string(self):
        return (
            f"PG:host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )

    # Importa o GeoJSON para uma tabela do PostGIS.
    def import_geojson(self, geojson_path, table_name=TABLE_NAME):
        source_ds = ogr.Open(str(geojson_path)) # Abre o arquivo GeoJSON usando OGR.
        if source_ds is None:
            raise RuntimeError(f"Nao foi possivel abrir o arquivo {geojson_path}.")

        source_layer = source_ds.GetLayer(0) # Obtém a primeira camada do GeoJSON (geralmente há apenas uma).
        if source_layer is None:
            raise RuntimeError("Nao foi possivel obter a camada do GeoJSON.")

        target_ds = ogr.Open(self.ogr_connection_string(), update=1) # Abre a conexão com o PostGIS usando OGR.
        if target_ds is None:
            raise RuntimeError("Nao foi possivel conectar ao PostGIS via OGR.")

        target_ds.ExecuteSQL(
            f'DROP TABLE IF EXISTS "{self.schema}"."{table_name}" CASCADE'
        ) # Remove a tabela de destino se ela já existir, para evitar erros de duplicação.

        options = [
            f"SCHEMA={self.schema}",
            "OVERWRITE=YES",
            "GEOMETRY_NAME=geom",
            "FID=ogc_fid",
            "PRECISION=NO",
        ] # Define as opções para a importação, como o nome do schema, se deve sobrescrever a tabela existente, o nome da coluna de geometria, o nome da coluna de ID e se deve manter a precisão original dos dados.
        imported_layer = target_ds.CopyLayer(source_layer, table_name, options) # Copia a camada do GeoJSON para o PostGIS, criando uma nova tabela com as opções definidas.
        if imported_layer is None:
            raise RuntimeError("Falha ao importar a camada para o PostGIS.")

        source_ds = None
        target_ds = None

    # Executa um comando SQL direto no PostGIS.
    def execute_sql(self, sql):
        target_ds = ogr.Open(self.ogr_connection_string(), update=1)
        if target_ds is None:
            raise RuntimeError("Nao foi possivel conectar ao PostGIS via OGR.")

        result = target_ds.ExecuteSQL(sql) # Executa a consulta SQL fornecida e armazena o resultado, que pode ser um conjunto de resultados ou None dependendo do tipo de consulta.
        if result is not None:
            target_ds.ReleaseResultSet(result)
        target_ds = None

    # Cria a view SQL que sera carregada no QGIS.
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

    # Prepara a URI de conexao usada pelo QGIS.
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


# Abre uma janela simples para pedir um texto ao usuario.
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


# Reune os parametros de conexao digitados no QGIS.
def ask_connection_parameters():
    return {
        "host": ask_text("PostGIS", "Host:", "localhost"),
        "port": ask_text("PostGIS", "Porta:", "5432"),
        "database": ask_text("PostGIS", "Banco de dados:"),
        "user": ask_text("PostGIS", "Usuario:"),
        "password": ask_text("PostGIS", "Senha:", password=True),
    }


###############   1.    Baixa o arquivo vetorial e salva em pasta temporaria.
def download_vector_data(url=DATA_URL):
    target_dir = Path(gettempdir()) / "projeto3_qgis_postgis"
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / "countries.geojson"
    urlretrieve(url, target_path)

    if not target_path.exists():
        raise RuntimeError("O download do dado vetorial falhou.")

    return target_path


# Carrega no QGIS a view criada pela consulta SQL.
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


# Executa o fluxo completo do projeto do inicio ao fim.
def run():
    try:
        # Pede os dados de conexao do banco.
        params = ask_connection_parameters()
        connection = PostGISManager(**params)

        # Baixa o dado vetorial escolhido para o projeto.
        print("Baixando dado vetorial...")
        geojson_path = download_vector_data()
        print(f"Arquivo salvo em: {geojson_path}")

        # Importa o arquivo baixado para uma tabela PostGIS.
        print("Importando dado para o PostGIS...")
        connection.import_geojson(geojson_path)
        print(f'Tabela criada: {SCHEMA}.{TABLE_NAME}')

        # Executa a SQL e cria uma view com o resultado.
        print("Executando consulta SQL no PostGIS...")
        connection.create_query_view()
        print(f'View criada: {SCHEMA}.{VIEW_NAME}')

        # Adiciona ao QGIS a camada baseada na view SQL.
        print("Carregando consulta SQL no QGIS...")
        layer = load_query_layer(connection)
        print(f'Camada adicionada ao QGIS: {layer.name()}')

        # Exibe uma mensagem final de sucesso.
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
        # Mostra o erro no QGIS e no terminal Python.
        QMessageBox.critical(
            iface.mainWindow(),
            "Projeto 3 - erro",
            str(exc),
        )
        print(f"Erro: {exc}")


# Inicia a execucao do script ao rodar o arquivo.
run()
