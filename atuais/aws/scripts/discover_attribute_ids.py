#!/usr/bin/env python3
# =============================================================================
# Script: Descobrir IDs de atributos no Jira Assets
# =============================================================================
# Uso:
#   python discover_attribute_ids.py --object-type 230
#   python discover_attribute_ids.py --object-type 152 --attribute-name "Name"
# =============================================================================

import os
import sys
import json
import argparse
import requests
from requests.auth import HTTPBasicAuth


def get_credentials():
    """Obtém credenciais do ambiente."""
    user = os.environ.get('JIRA_USER')
    password = os.environ.get('JIRA_PASSWORD')
    
    if not user or not password:
        print("ERRO: Defina JIRA_USER e JIRA_PASSWORD")
        sys.exit(1)
    
    return user, password


def get_object_type_attributes(workspace_id: str, object_type_id: int, auth: HTTPBasicAuth, proxies: dict = None):
    """Busca todos os atributos de um Object Type."""
    url = f"https://api.atlassian.com/jsm/insight/workspace/{workspace_id}/v1/objecttype/{object_type_id}/attributes"
    
    response = requests.get(url, auth=auth, proxies=proxies)
    response.raise_for_status()
    
    return response.json()


def main():
    parser = argparse.ArgumentParser(description='Descobrir IDs de atributos no Jira Assets')
    parser.add_argument('--workspace', default='76827f8b-4d96-46a6-abf2-f592d6b4b2d9',
                        help='Workspace ID do Jira Assets')
    parser.add_argument('--object-type', type=int, required=True,
                        help='ID do Object Type (ex: 121=Servidor, 230=Interface de Rede)')
    parser.add_argument('--attribute-name', default=None,
                        help='Filtrar por nome do atributo')
    parser.add_argument('--proxy', default=None,
                        help='Proxy HTTP (ex: http://10.54.24.184:3128)')
    parser.add_argument('--output', choices=['table', 'json'], default='table',
                        help='Formato de saída')
    
    args = parser.parse_args()
    
    user, password = get_credentials()
    auth = HTTPBasicAuth(user, password)
    
    proxies = None
    if args.proxy:
        proxies = {'http': args.proxy, 'https': args.proxy}
    
    print(f"\n{'='*70}")
    print(f"Object Type ID: {args.object_type}")
    print(f"{'='*70}\n")
    
    try:
        attributes = get_object_type_attributes(args.workspace, args.object_type, auth, proxies)
    except requests.exceptions.HTTPError as e:
        print(f"ERRO: {e}")
        sys.exit(1)
    
    if args.attribute_name:
        attributes = [a for a in attributes if args.attribute_name.lower() in a.get('name', '').lower()]
    
    if args.output == 'json':
        print(json.dumps(attributes, indent=2, ensure_ascii=False))
    else:
        # Formato tabela
        print(f"{'ID':<10} {'Nome':<30} {'Tipo':<15} {'Obrigatório':<12}")
        print("-" * 70)
        
        for attr in attributes:
            attr_id = attr.get('id', 'N/A')
            name = attr.get('name', 'N/A')[:28]
            
            # Determinar tipo
            default_type = attr.get('defaultType', {})
            tipo = default_type.get('name', 'Reference') if default_type else 'Reference'
            
            # Verificar se é obrigatório
            min_card = attr.get('minimumCardinality', 0)
            obrigatorio = 'Sim' if min_card > 0 else 'Não'
            
            print(f"{attr_id:<10} {name:<30} {tipo:<15} {obrigatorio:<12}")
    
    print(f"\nTotal: {len(attributes)} atributos\n")


if __name__ == '__main__':
    main()
