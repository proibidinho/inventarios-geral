# =============================================================================
# Filter Plugin: Transformacao Ansible Facts -> Jira Assets (CMDB)
# =============================================================================
# Le o dicionario ansible_facts (gather_facts) de um host (Linux ou Windows)
# e devolve "cloud_data" no mesmo formato consumido por update_asset_cmdb.
# Mantemos o codigo o mais simples possivel: zero logica de mapeamento de
# valores aqui dentro. Toda a traducao "valor coletado -> ID do CMDB" fica no
# YAML vars/mapeamento_facts_cmdb.yml.
# =============================================================================
from __future__ import absolute_import, division, print_function
__metaclass__ = type


def _get(facts, *keys):
    """Retorna o primeiro fact nao-vazio dentre as chaves dadas."""
    for k in keys:
        v = facts.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def _normalize_so(facts):
    """Mapeia ansible_os_family / system para os valores aceitos no YAML."""
    family = str(_get(facts, "ansible_os_family", "os_family") or "").lower()
    system = str(_get(facts, "ansible_system", "system") or "").lower()

    if "windows" in family or "win32" in system:
        return "Windows"
    if "solaris" in family or "sunos" in family:
        return "SOLARIS"
    if "hp-ux" in family or "hpux" in family:
        return "HPUX"
    if "darwin" in family:
        return "MacOS"
    # Familias Linux conhecidas + fallback
    return "Linux"


def _extract_cpu_model(facts):
    """Extrai o modelo da CPU (texto livre) - util para o campo CPU Count/CPU."""
    processors = _get(facts, "ansible_processor", "processor") or []
    if isinstance(processors, list):
        # Procurar o item com nome real do processador (contem "(R)" ou "GHz" ou "CPU")
        for item in processors:
            if isinstance(item, str) and ("(R)" in item or "GHz" in item or " CPU " in item):
                return item.strip()
        # Fallback - qualquer item com Intel/AMD/Xeon/EPYC e que seja "longo"
        for item in processors:
            if isinstance(item, str) and len(item) > 15 and any(
                kw in item for kw in ("Intel", "AMD", "Xeon", "EPYC", "Ryzen")
            ):
                return item.strip()
    return ""


def _extract_ips(facts):
    """Extrai IPs em formato [{tipo,ip}] suportando Linux e Windows facts."""
    ips = []
    seen = set()

    def add(ip):
        if ip and ip not in seen:
            seen.add(ip)
            ips.append({"tipo": "privado", "ip": ip})

    # Linux: ansible_default_ipv4
    d4 = _get(facts, "ansible_default_ipv4") or {}
    if isinstance(d4, dict):
        add(d4.get("address"))

    # Linux: ansible_all_ipv4_addresses
    for ip in (_get(facts, "ansible_all_ipv4_addresses") or []):
        add(ip)

    # Windows: interfaces[].ipv4.address
    for iface in (_get(facts, "interfaces", "ansible_interfaces") or []):
        if isinstance(iface, dict):
            ipv4 = iface.get("ipv4") or {}
            add(ipv4.get("address") if isinstance(ipv4, dict) else None)

    return ips


def _extract_disco_gb(facts):
    """Soma o tamanho total dos mounts (Linux). Windows facts padrao nao traz."""
    total_bytes = 0
    for m in (_get(facts, "ansible_mounts") or []):
        if isinstance(m, dict):
            total_bytes += int(m.get("size_total") or 0)
    if not total_bytes:
        return None
    return round(total_bytes / (1024 ** 3), 1)


def transform_facts_host(host_facts, target_name=None, datacenter=None):
    """
    Converte ansible_facts em cloud_data para envio ao CMDB.

    Args:
        host_facts: dict com os facts coletados (gather_facts) do servidor.
        target_name: opcional - nome recebido via extra-vars (fallback).
        datacenter: opcional - nome do datacenter fisico (ex.: "Lapa") via extra-var.

    Returns:
        dict cloud_data (mesmo formato do transform_azure_host).
    """
    if not isinstance(host_facts, dict):
        host_facts = {}

    hostname = _get(host_facts, "ansible_hostname", "hostname") or target_name or ""
    fqdn = _get(host_facts, "ansible_fqdn", "fqdn") or hostname

    so = _normalize_so(host_facts)
    ram_mb = _get(host_facts, "ansible_memtotal_mb", "memtotal_mb")
    vcpus = _get(host_facts, "ansible_processor_vcpus", "processor_vcpus")
    cpu_model = _extract_cpu_model(host_facts)
    ips = _extract_ips(host_facts)
    disco_gb = _extract_disco_gb(host_facts)

    virt_role = str(_get(host_facts, "ansible_virtualization_role", "virtualization_role") or "").lower()
    tipo_infra = "MAQUINA VIRTUAL" if virt_role == "guest" else "SERVIDOR FISICO"

    # Grupo Solucionador - Infra (fixo por SO)
    grupo = "Windows" if so == "Windows" else "Infracloud"

    cloud_data = {
        # Identificacao
        "name_cloud": hostname,
        "fqdn_cloud": fqdn,

        # SO (mapeado no YAML para referencedType)
        "sistema_operacional_cloud": so,

        # Hardware
        "memoria_ram_cloud": int(ram_mb) if ram_mb else None,
        "cpu_count_cloud": str(vcpus) if vcpus else None,
        "cpu_model_cloud": cpu_model or None,
        "capacidade_disco_cloud": "{} GB".format(disco_gb) if disco_gb else None,

        # Rede
        "interface_rede_cloud": ips,

        # Categoria / Tipo
        "tipo_infraestrutura_cloud": tipo_infra,

        # Status
        "status_cloud": "Em uso",
        "status_discovery_cloud": "Running",

        # Operacao
        "last_user_cloud": "Ansible",
        "grupo_solucionador_infra_cloud": grupo,

        # Booleanos fixos (mesma regra do Azure)
        "sox_cloud": "false",
        "ipe_cloud": "false",
        "disaster_recovery_cloud": "false",

        # Versao do SO - texto livre (caso queiram usar como Versao SO livre)
        "versao_so_cloud": _get(host_facts, "ansible_distribution_version",
                                "distribution_version", "ansible_distribution"),

        # Datacenter - via extra-var "datacenter_target" (opcional)
        "datacenter_cloud": datacenter or None,
    }

    # Remover None / strings vazias / listas vazias
    return {k: v for k, v in cloud_data.items() if v not in (None, "", [], {})}


class FilterModule(object):
    """Ansible filter plugin: facts -> CMDB."""

    def filters(self):
        return {
            "transform_facts_host": transform_facts_host,
        }
