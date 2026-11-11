"""Update the project classifier in place while preserving its credential bindings."""
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def update():
    config = dotenv_values(ROOT / '.env')
    base = config['LANGFLOW_URL']
    if urlsplit(base).hostname not in {'127.0.0.1', 'localhost', '::1'}:
        raise RuntimeError('La actualización exige un Langflow local.')
    endpoint = '/api/v1/flows/' + config['LANGFLOW_FLOW_ID']
    code = (ROOT / 'integrations/langflow/cloud_classifier_model.py').read_text(encoding='utf-8')
    if not config.get('LANGFLOW_API_KEY'):
        raise RuntimeError('La actualización requiere la credencial Langflow existente.')
    with httpx.Client(base_url=base, timeout=20, trust_env=False,
                      headers={'x-api-key': config['LANGFLOW_API_KEY']}) as client:
        graph = client.get(endpoint).raise_for_status().json()['data']
        models = [item for item in graph['nodes'] if item['data']['type'] == 'SocCloudModel']
        if len(models) != 1:
            raise RuntimeError('El flujo activo debe tener exactamente un componente SOC cloud.')
        node = models[0]['data']['node']['template']
        fields = [node[name] for name in ('groq_api_key', 'gemini_api_key')]
        bindings = tuple(field.get('value') for field in fields)
        if any(not field.get('load_from_db') or not isinstance(value, str) or not any(char.isalnum() for char in value)
               for field, value in zip(fields, bindings)):
            raise RuntimeError('Langflow no devolvió referencias de credenciales que puedan conservarse.')
        if node['code']['value'] == code:
            print('El componente del clasificador ya está actualizado.')
            return
        node['code']['value'] = code
        client.patch(endpoint, json={'data': graph}).raise_for_status()
        current = client.get(endpoint).raise_for_status().json()['data']
        current_node = next(item for item in current['nodes'] if item['id'] == models[0]['id'])['data']['node']['template']
        if current_node['code']['value'] != code or bindings != tuple(current_node[name].get('value') for name in ('groq_api_key', 'gemini_api_key')):
            raise RuntimeError('La verificación del flujo actualizado falló.')
    print('Componente del clasificador actualizado. Se conservaron el flujo y sus credenciales.')


if __name__ == '__main__':
    update()
