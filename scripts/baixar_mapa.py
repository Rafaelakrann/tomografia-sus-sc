import gzip
import json
from pathlib import Path
from urllib.request import urlopen

URL = ("https://servicodados.ibge.gov.br/api/v3/malhas/estados/42"
       "?formato=application/vnd.geo+json&intrarregiao=municipio&qualidade=intermediaria")
destino = Path("dados/processados/municipios_sc.geojson")

print("Baixando a malha de municípios de SC do IBGE...")
with urlopen(URL, timeout=120) as resposta:
    conteudo = resposta.read()

# O IBGE envia o arquivo compactado em gzip; os dois primeiros bytes indicam isso
if conteudo[:2] == b"\x1f\x8b":
    conteudo = gzip.decompress(conteudo)

mapa = json.loads(conteudo.decode("utf-8"))

destino.write_text(json.dumps(mapa), encoding="utf-8")
print(f"{len(mapa['features'])} municípios salvos em {destino}")