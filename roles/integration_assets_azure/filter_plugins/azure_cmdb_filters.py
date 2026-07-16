# =============================================================================
# Filter Plugin: Transformacao Azure -> Jira Assets
# =============================================================================
# Este modulo contem funcoes para transformar dados do Azure (AAP inventory)
# para o formato esperado pelo Jira Assets (CMDB).
# =============================================================================

from __future__ import absolute_import, division, print_function
__metaclass__ = type


def search_attribute(value, object_attribute_map):
    """Busca um atributo no mapeamento pela chave_cloud."""
    return list(filter(lambda x: x.get("chave_cloud") == value, object_attribute_map))


def extract_os_from_azure(host_vars):
    """
    Extrai o sistema operacional dos dados do Azure.
    
    Verifica:
    - os_disk.operating_system_type
    - os_profile.system
    - image.offer/publisher
    """
    # Verificar os_disk
    os_disk = host_vars.get("os_disk", {})
    os_type = os_disk.get("operating_system_type", "").lower()
    
    if os_type == "windows":
        return "Windows"
    elif os_type == "linux":
        return "Linux"
    
    # Verificar os_profile
    os_profile = host_vars.get("os_profile", {})
    system = os_profile.get("system", "").lower()
    
    if system == "windows":
        return "Windows"
    elif system == "linux":
        return "Linux"
    
    # Verificar image
    image = host_vars.get("image", {})
    offer = image.get("offer", "").lower()
    publisher = image.get("publisher", "").lower()
    
    windows_keywords = ["windows", "windowsserver", "win"]
    linux_keywords = ["ubuntu", "centos", "rhel", "debian", "suse", "redhat", "linux", "alma", "rocky"]
    
    for kw in windows_keywords:
        if kw in offer or kw in publisher:
            return "Windows"
    
    for kw in linux_keywords:
        if kw in offer or kw in publisher:
            return "Linux"
    
    # Default
    return "Linux"


def map_azure_status_to_cmdb(powerstate):
    """Mapeia o powerstate do Azure para o status do CMDB."""
    status_map = {
        "running": "Em uso",
        "starting": "Reservado",
        "deallocating": "Desativado",
        "deallocated": "Desativado",
        "stopped": "Desativado",
        "stopping": "Desativado",
    }
    return status_map.get(powerstate.lower() if powerstate else "", "Em uso")

def get_tag(host_vars, *keys):
    """
    Retorna o valor da primeira tag encontrada (case-insensitive),
    buscando em host_vars["tags"]. Util para tags Azure "ef_*".
    """
    tags = host_vars.get("tags", {}) or {}
    tags_lower = {str(k).lower(): v for k, v in tags.items()}
    for k in keys:
        v = tags_lower.get(k.lower())
        if v not in (None, ""):
            return v
    return None


def parse_bool_tag(value):
    """Converte string de tag em booleano para campos Boolean do CMDB."""
    if value is None:
        return False
    s = str(value).strip().lower()
    return s in ("true", "sim", "yes", "1", "s", "y")


def determine_ambiente_azure(host_vars):
    """Determina o Ambiente com base nas tags do Azure (case-insensitive)."""
    ambiente_tag = get_tag(
        host_vars,
        "ef_ambiente", "environment", "ambiente",
    ) or ""

    if not ambiente_tag:
        return None

    ambiente_lower = str(ambiente_tag).lower()

    # Nao producao - nao preenche
    if any(x in ambiente_lower for x in ["nonprod", "non-prod", "dev", "hml", "staging", "homolog", "qa", "test", "sandbox"]):
        return None

    # Producao
    if any(x in ambiente_lower for x in ["prod", "prd", "production"]):
        return "Produção"

    return None

def transform_azure_host(host_vars):
    """
    Transforma os dados de um host Azure (do AAP inventory) para cloud_data.
    
    Args:
        host_vars: Dicionario com as variaveis do host do inventario AAP
    
    Returns:
        Dicionario no formato cloud_data para o playbook
    """
    # Extrair informacoes basicas
    name = host_vars.get("azure_vm_name") or host_vars.get("name") or host_vars.get("computer_name", "")
    
    # # Extrair FQDN - prioridade: public_dns_hostnames > public_dns_name > computer_name > name
    # fqdn = None
    # public_dns_hostnames = host_vars.get("public_dns_hostnames", [])
    # if public_dns_hostnames and len(public_dns_hostnames) > 0:
    #     fqdn = public_dns_hostnames[0]
    # elif host_vars.get("public_dns_name"):
    #     fqdn = host_vars.get("public_dns_name")
    # elif host_vars.get("computer_name"):
    #     fqdn = host_vars.get("computer_name")
    # else:
    #     fqdn = name
    
    # Extrair informacoes basicas
    name = host_vars.get("azure_vm_name") or host_vars.get("name") or host_vars.get("computer_name", "")
    vmid = host_vars.get("vmid", "")
    
    # Extrair FQDN - prioridade: public_dns_hostnames > public_dns_name > computer_name > name
    fqdn = None
    public_dns_hostnames = host_vars.get("public_dns_hostnames", [])
    if public_dns_hostnames and len(public_dns_hostnames) > 0:
        fqdn = public_dns_hostnames[0]
    elif host_vars.get("public_dns_name"):
        fqdn = host_vars.get("public_dns_name")
    
    # Se nao tem FQDN real, usar name-vmid para garantir unicidade
    if fqdn:
        name_cloud = name
    else:
        fqdn = name  # FQDN fica igual ao name
        if vmid:
            name_cloud = f"{name}-{vmid}"
        else:
            name_cloud = name
    
    # Extrair IPs
    private_ips = host_vars.get("private_ipv4_addresses", [])
    public_ips = host_vars.get("public_ipv4_address", [])
    
    ips = []
    for ip in private_ips:
        if ip:
            ips.append({"tipo": "privado", "ip": ip})
    for ip in public_ips:
        if ip:
            ips.append({"tipo": "publico", "ip": ip})
    
    # Extrair disco
    os_disk = host_vars.get("os_disk", {})
    data_disks = host_vars.get("data_disks", [])
    
    # Calcular tamanho total de disco (se disponivel)
    disk_size = None
    
    # Extrair RAM e CPU do virtual_machine_size (nao disponivel diretamente)
    vm_size = host_vars.get("virtual_machine_size", "")

    # Tags Azure padrao "ef_*" -> chaves cloud_data (case-insensitive)
    tag_owner    = get_tag(host_vars, "ef_owner")
    tag_sistema  = get_tag(host_vars, "ef_projeto")
    tag_produto  = get_tag(host_vars, "ef_produto")
    tag_dr       = get_tag(host_vars, "ef_recuperacao_de_desastre", "ef_dr")
    tag_regiao   = get_tag(host_vars, "ef_regiao", "ef_region")
    tag_iac      = get_tag(host_vars, "ef_iac")

    # Grupo Solucionador - Infra: fixo por SO (Windows -> Windows, Linux -> Infracloud)
    so_detectado = extract_os_from_azure(host_vars)
    grupo_solucionador = "Windows" if so_detectado == "Windows" else "Infracloud"

    # Montar cloud_data
    cloud_data = {
        # Identificacao
        "name_cloud": name_cloud,
        "fqdn_cloud": fqdn,
        
        # Sistema Operacional
        "sistema_operacional_cloud": extract_os_from_azure(host_vars),
        
        # Hardware - Azure nao fornece diretamente, usar vm_size como modelo
        "modelo_servidor_cloud": vm_size,
        
        # Rede
        "interface_rede_cloud": ips,
        
        # Status
        "status_cloud": map_azure_status_to_cmdb(host_vars.get("powerstate", "running")),
        
        # Tipo/Modelo (valores fixos para Azure)
        "tipo_servidor_cloud": "Virtual",
        "tipo_infraestrutura_cloud": "CLOUD PUBLICA",
        
        # Datacenter fixo Azure
        "datacenter_cloud": "Azure",
        
        # Discovery
        "status_discovery_cloud": "Running",
        
        # Booleanos fixos
        "sox_cloud": "false",
        "ipe_cloud": "false",
        
        # Ambiente (baseado em tags)
        "ambiente_cloud": determine_ambiente_azure(host_vars),

        # Last User (sempre Ansible, pois esta integracao escreve no CMDB)
        "last_user_cloud": "Ansible",

        # Grupo Solucionador - Infra (fixo por SO)
        "grupo_solucionador_infra_cloud": grupo_solucionador,

        # Tags Azure "ef_*" mapeadas (validar valores no CMDB antes de ativar no YAML)
        "owner_cloud": tag_owner,
        "sistema_cloud": tag_sistema,
        "produto_cloud": tag_produto,
        "vcenter_cloud": tag_regiao,
        "iac_cloud": tag_iac,
        "disaster_recovery_cloud": parse_bool_tag(tag_dr) if tag_dr is not None else None,
        
        # Metadados Azure (para referencia)
        "azure_vm_id": host_vars.get("vmid", ""),
        "azure_resource_group": host_vars.get("resource_group", ""),
        "azure_location": host_vars.get("azure_location") or host_vars.get("location", ""),
        "azure_subscription": extract_subscription_from_id(host_vars.get("id", "")),
        "azure_tags": host_vars.get("tags", {}),
        # Conta Cloud (Resource Group)
        "conta_cloud_cloud": host_vars.get("resource_group", ""),
    }
    
    # Remover valores None ou vazios
    cloud_data = {k: v for k, v in cloud_data.items() if v is not None and v != ""}
    
    return cloud_data


def extract_subscription_from_id(resource_id):
    """Extrai o subscription ID do resource ID do Azure."""
    if not resource_id:
        return ""
    # /subscriptions/XXXX/resourceGroups/...
    parts = resource_id.split("/")
    try:
        idx = parts.index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return ""


def update_asset(cloud_data, object_attribute_map):
    """
    Transforma cloud_data no formato de payload para criar/atualizar no Jira Assets.
    """
    data = {
        "attributes": [],
        "objectTypeId": 121
    }
    
    for field, value in cloud_data.items():
        if value is None or value == "":
            continue
        
        # Campos de metadados Azure nao sao enviados ao CMDB
        if field.startswith("azure_"):
            continue
        
        # Buscar o atributo no mapeamento
        obj_attr_list = search_attribute(field, object_attribute_map)
        
        if not obj_attr_list:
            continue
        
        obj_attr = obj_attr_list[0]
        attr_type = obj_attr.get("tipo", "text")
        attr_id = str(obj_attr.get("id"))
        
        attribute_entry = {
            "objectTypeAttributeId": attr_id,
            "objectAttributeValues": []
        }
        
        # Processar conforme o tipo do atributo
        if attr_type == "objeto":
            valores = obj_attr.get("valores", [])
            matched = next((v for v in valores if v.get("value") == value), None)

            # Fallback: se o valor recebido nao esta mapeado, usa o "valor_fallback"
            if not matched:
                valor_fallback = obj_attr.get("valor_fallback")
                if valor_fallback:
                    matched = next((v for v in valores if v.get("value") == valor_fallback), None)

            if matched:
                attribute_entry["objectAttributeValues"] = [
                    {"value": str(matched.get("referencedType"))}
                ]
            else:
                continue
        
        elif attr_type == "status":
            valores = obj_attr.get("valores", [])
            matched = next((v for v in valores if v.get("value") == value), None)
            
            if matched:
                attribute_entry["objectAttributeValues"] = [
                    {"value": str(matched.get("referencedType"))}
                ]
            else:
                continue
        
        elif attr_type == "objeto_lista":
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item:
                        attribute_entry["objectAttributeValues"].append(
                            {"value": item}
                        )
                    elif isinstance(item, dict):
                        item_id = item.get("id") or item.get("referencedType")
                        if item_id:
                            attribute_entry["objectAttributeValues"].append(
                                {"value": str(item_id)}
                            )
            if not attribute_entry["objectAttributeValues"]:
                continue
        
        elif attr_type == "boolean":
            attribute_entry["objectAttributeValues"] = [
                {"value": str(value).lower()}
            ]
        
        elif attr_type == "integer":
            attribute_entry["objectAttributeValues"] = [
                {"value": str(value)}
            ]
        
        elif attr_type == "select":
            # Para Select, verificar se o valor existe nas opcoes (se definido no mapeamento)
            # Se nao tiver lista de valores validos, aceita qualquer valor
            valores_validos = obj_attr.get("valores_validos", [])
            if valores_validos and value not in valores_validos:
                # Valor nao existe no menu, pular este atributo
                continue
            attribute_entry["objectAttributeValues"] = [
                {"value": str(value)}
            ]
        
        else:  # text e outros
            attribute_entry["objectAttributeValues"] = [
                {"value": str(value)}
            ]
        
        if attribute_entry["objectAttributeValues"]:
            data["attributes"].append(attribute_entry)
    
    # Pos-processamento: garantir fallback para atributos com "valor_fallback"
    # ou "valor_fixo" que nao foram preenchidos (ex.: tag ausente no host Azure).
    # Permite que qualquer campo declare seu default direto no YAML, sem mexer
    # no transform (Python).
    ids_ja_enviados = {a["objectTypeAttributeId"] for a in data["attributes"]}
    for obj_attr in object_attribute_map:
        attr_id = str(obj_attr.get("id"))
        if attr_id in ids_ja_enviados:
            continue

        valor_default = obj_attr.get("valor_fallback")
        if valor_default is None:
            valor_default = obj_attr.get("valor_fixo")
        if valor_default is None:
            continue

        tipo = obj_attr.get("tipo")

        # Tipo objeto: traduzir o "value" para o "referencedType" via lista valores
        if tipo == "objeto":
            valores = obj_attr.get("valores", [])
            matched = next((v for v in valores if v.get("value") == valor_default), None)
            if matched:
                data["attributes"].append({
                    "objectTypeAttributeId": attr_id,
                    "objectAttributeValues": [{"value": str(matched.get("referencedType"))}]
                })
        # Tipo boolean: enviar "true"/"false"
        elif tipo == "boolean":
            data["attributes"].append({
                "objectTypeAttributeId": attr_id,
                "objectAttributeValues": [{"value": str(bool(valor_default)).lower()}]
            })
        # Tipos text/select/integer: enviar o valor como string
        elif tipo in ("text", "select", "integer"):
            data["attributes"].append({
                "objectTypeAttributeId": attr_id,
                "objectAttributeValues": [{"value": str(valor_default)}]
            })

    return data


def batch_transform_hosts(hosts_vars_list):
    """
    Transforma uma lista de hosts Azure para o formato cloud_data.
    """
    results = []
    for host_vars in hosts_vars_list:
        cloud_data = transform_azure_host(host_vars)
        results.append(cloud_data)
    return results


class FilterModule(object):
    """Ansible filter plugin para transformacao Azure -> Jira Assets."""
    
    def filters(self):
        return {
            'update_asset_azure': update_asset,
            'transform_azure_host': transform_azure_host,
            'batch_transform_azure_hosts': batch_transform_hosts,
            'extract_os_from_azure': extract_os_from_azure,
            'map_azure_status_to_cmdb': map_azure_status_to_cmdb,
            'extract_subscription_from_id': extract_subscription_from_id,
            'search_attribute_azure': search_attribute,
        }

