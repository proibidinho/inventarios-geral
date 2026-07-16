# =============================================================================
# Filter Plugin: Transformação AWS → Jira Assets
# =============================================================================

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import json
from typing import Dict, List, Optional


def search_attribute(value: str, object_attribute_map: List[Dict]) -> List[Dict]:
    """Busca um atributo no mapeamento pela chave_cloud."""
    return list(filter(lambda x: x.get("chave_cloud") == value, object_attribute_map))


def map_aws_status_to_cmdb(aws_state: str) -> str:
    """Mapeia o status da AWS para o status do CMDB."""
    status_map = {
        "running": "Em uso",
        "pending": "Reservado",
        "stopping": "Desativado",
        "stopped": "Desativado",
        "shutting-down": "Desativado",
        "terminated": "Desativado",
    }
    return status_map.get(aws_state.lower() if aws_state else "", "Em uso")


def extract_os_from_platform(platform: str) -> str:
    """Extrai o sistema operacional a partir do campo platform da AWS."""
    if not platform:
        return "Linux"
    
    platform_lower = platform.lower()
    if "windows" in platform_lower:
        return "Windows"
    
    return "Linux"


def is_eks_node(variables: Dict) -> bool:
    """
    Detecta se o host eh um no de cluster EKS.
    Sinal principal: iam_instance_profile.arn contem ':instance-profile/eks-'.
    Sinais complementares: tags aws:eks:*, eks:cluster-name, kubernetes.io/cluster/*.
    """
    if not variables:
        return False

    iam_profile = variables.get("iam_instance_profile") or {}
    if isinstance(iam_profile, dict):
        arn = iam_profile.get("arn", "") or ""
        if ":instance-profile/eks-" in arn:
            return True

    tags = variables.get("tags") or {}
    if not isinstance(tags, dict):
        return False

    if "aws:eks:cluster-name" in tags or "eks:cluster-name" in tags:
        return True
    for key in tags:
        if str(key).startswith("kubernetes.io/cluster/"):
            return True

    return False


def determine_ambiente_aws(variables: Dict) -> Optional[str]:
    """
    Determina o Ambiente com base nas tags ou environment.
    """
    tags = variables.get("tags", {})
    ambiente_tag = (
        tags.get("ef_ambiente") or 
        tags.get("environment") or 
        tags.get("Environment") or
        variables.get("environment") or
        ""
    )
    
    if not ambiente_tag or ambiente_tag == "undefined":
        return "Produção"
    
    ambiente_lower = ambiente_tag.lower()
    
    # Não produção - retorna None para não preencher
    if any(x in ambiente_lower for x in ["nonprod", "non-prod", "dev", "hml", "staging", "homolog", "qa", "test", "sandbox"]):
        return None
    
    # Produção
    if any(x in ambiente_lower for x in ["prod", "prd", "production"]):
        return "Produção"
    
    return "Produção"


def transform_aws_host(host_data: Dict) -> Dict:
    """
    Transforma os dados de um host AWS (do AAP) para o formato cloud_data.
    """
    # Parsear variables (pode ser string JSON ou dict)
    variables_str = host_data.get("variables", "{}")
    try:
        variables = json.loads(variables_str) if isinstance(variables_str, str) else variables_str
    except json.JSONDecodeError:
        variables = {}
    
    if not variables:
        return {}
    
    tags = variables.get("tags", {})
    
    # Instance ID (usado para garantir unicidade)
    instance_id = variables.get("instance_id", "")
    
    # FQDN = private_dns_name (se existir)
    fqdn = variables.get("private_dns_name", "").strip()
    
    # NAME - lógica:
    # 1. Se tem private_dns_name → usa (já é único)
    # 2. Se não tem → concatena vm_name/tags.Name + instance_id
    if fqdn:
        name = fqdn
    else:
        base_name = variables.get("vm_name", "").strip()
        if not base_name:
            base_name = tags.get("Name", "").strip()
        if not base_name:
            base_name = host_data.get("name", "").strip()
        
        # Concatenar instance_id para garantir unicidade
        if base_name and instance_id:
            name = f"{base_name}-{instance_id}"
        elif instance_id:
            name = instance_id
        else:
            name = base_name
    
    # Account ID (Conta Cloud)
    account_id = variables.get("account_id") or variables.get("owner_id", "")
    
    # IPs - filtrar valores vazios e "N/A"
    private_ip = variables.get("private_ip") or variables.get("private_ip_address", "")
    public_ip = variables.get("public_ip") or variables.get("public_ip_address", "")
    
    ips = []
    if private_ip and private_ip not in ("", "N/A", "n/a"):
        ips.append({"tipo": "privado", "ip": private_ip})
    if public_ip and public_ip not in ("", "N/A", "n/a"):
        ips.append({"tipo": "publico", "ip": public_ip})
    
    # CPU - calcular vCPUs
    cpu_options = variables.get("cpu_options", {})
    core_count = cpu_options.get("core_count", 0)
    threads_per_core = cpu_options.get("threads_per_core", 1)
    vcpus = core_count * threads_per_core if core_count else None
    
    # Instance Type (Modelo do Servidor)
    instance_type = variables.get("instance_type", "")
    
    # Status
    state = variables.get("state", "running")
    
    # Sistema Operacional
    platform = variables.get("platform") or variables.get("platform_details") or ""
    
    # Ambiente
    ambiente = determine_ambiente_aws(variables)

    # Sistema (CMDB) - vem da tag ef_cmdb (ex.: "GDA-2730753").
    # Jira Assets aceita objectKey diretamente no value de campo Reference.
    sistema_cmdb = tags.get("ef_cmdb", "").strip()

    # Região (para debug)
    region = variables.get("region", "")
    availability_zone = variables.get("availability_zone", "")
    
    # Montar cloud_data
    cloud_data = {
        # Conta Cloud (Account ID da AWS)
        "conta_cloud_cloud": account_id if account_id else None,
        
        # Ambiente
        "ambiente_cloud": ambiente,

        # Sistema (Reference no CMDB - passa objectKey vindo da tag ef_cmdb)
        "sistema_cloud": sistema_cmdb if sistema_cmdb else None,
        
        # Identificação
        "name_cloud": name,
        "fqdn_cloud": fqdn if fqdn else None,
        
        # Sistema Operacional
        "sistema_operacional_cloud": extract_os_from_platform(platform),
        
        # Hardware
        "cpu_count_cloud": str(vcpus) if vcpus else None,
        
        # Modelo do Servidor (instance_type)
        "modelo_servidor_cloud": instance_type if instance_type else None,
        
        # Rede
        "interface_rede_cloud": ips if ips else None,
        
        # Status
        "status_cloud": map_aws_status_to_cmdb(state),
        
        # Tipo de Servidor (select)
        "tipo_servidor_cloud": "Cloud Pública",
        
        # Tipo de Infraestrutura (referência)
        "tipo_infraestrutura_cloud": "CLOUD PUBLICA",
        
        # Datacenter
        "datacenter_cloud": "AWS",
        
        #Usuario Ansible
        "usuario": "Ansible",
        
        # Metadados AWS (prefixo _ = não enviados ao CMDB)
        "_aws_instance_id": instance_id,
        "_aws_instance_type": instance_type,
        "_aws_region": region,
        "_aws_availability_zone": availability_zone,
        "_aws_tags_name": tags.get("Name", ""),
    }
    
    # Remover valores None
    cloud_data = {k: v for k, v in cloud_data.items() if v is not None}
    
    return cloud_data


def batch_transform_aws_hosts(hosts: List[Dict]) -> List[Dict]:
    """Transforma uma lista de hosts AWS (do AAP) para o formato cloud_data."""
    results = []
    
    for host in hosts:
        if not host.get("enabled", True):
            continue

        # Parse rapido de variables para checar se eh no EKS (skip antecipado)
        variables_str = host.get("variables", "{}")
        try:
            variables = json.loads(variables_str) if isinstance(variables_str, str) else variables_str
        except json.JSONDecodeError:
            variables = {}

        # Nos de cluster EKS - ignorados ate o time CMDB definir tratamento
        if is_eks_node(variables):
            continue

        cloud_data = transform_aws_host(host)
        
        if cloud_data.get("name_cloud"):
            results.append(cloud_data)
    
    return results


def update_asset(cloud_data: Dict, object_attribute_map: List[Dict]) -> Dict:
    """Transforma cloud_data no formato de payload para criar/atualizar no Jira Assets."""
    data = {
        "attributes": [],
        "objectTypeId": 121
    }

    for field, value in cloud_data.items():
        if value is None or value == "":
            continue

        # Campos de metadados (começam com _) não são enviados ao CMDB
        if field.startswith("_"):
            continue

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

        if attr_type == "objeto":
            valores = obj_attr.get("valores", [])
            matched = next((v for v in valores if v.get("value") == value), None)
            if matched:
                attribute_entry["objectAttributeValues"] = [
                    {"value": str(matched.get("referencedType"))}
                ]
            else:
                # Valor não encontrado - skip
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
            # Interface de Rede é tratada separadamente
            continue

        elif attr_type == "boolean":
            attribute_entry["objectAttributeValues"] = [{"value": str(value).lower()}]

        elif attr_type == "integer":
            attribute_entry["objectAttributeValues"] = [{"value": str(value)}]

        elif attr_type == "select":
            # Select com validação - se tiver lista de valores, só inclui se existir
            valores = obj_attr.get("valores", [])
            if valores:
                # Tem lista de valores - verificar se existe
                matched = next((v for v in valores if v.get("value") == value), None)
                if matched:
                    attribute_entry["objectAttributeValues"] = [{"value": str(value)}]
                else:
                    # Valor não existe na lista - skip
                    continue
            else:
                # Sem lista de valores definida - skip para evitar erro
                continue

        else:
            # text e outros
            attribute_entry["objectAttributeValues"] = [{"value": str(value)}]

        if attribute_entry["objectAttributeValues"]:
            data["attributes"].append(attribute_entry)

    return data


class FilterModule(object):
    """Ansible filter plugin para transformação AWS → Jira Assets."""

    def filters(self):
        return {
            'update_asset': update_asset,
            'transform_aws_host': transform_aws_host,
            'batch_transform_aws_hosts': batch_transform_aws_hosts,
            'map_aws_status_to_cmdb': map_aws_status_to_cmdb,
            'extract_os_from_platform': extract_os_from_platform,
            'determine_ambiente_aws': determine_ambiente_aws,
            'is_eks_node': is_eks_node,
            'search_attribute': search_attribute,
        }
