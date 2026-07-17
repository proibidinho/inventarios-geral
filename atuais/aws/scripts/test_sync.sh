#!/bin/bash
# =============================================================================
# Script: Teste Rápido de Sincronização GCP → CMDB
# =============================================================================
# Este script facilita o teste do playbook com uma VM específica do GCP.
#
# Uso:
#   ./test_sync.sh vm-bastion-linux southamerica-east1-c claro-infracloud
#
# Ou modo interativo:
#   ./test_sync.sh
# =============================================================================

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Diretório do script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}"
echo "════════════════════════════════════════════════════════════════"
echo "         TESTE DE SINCRONIZAÇÃO GCP → JIRA ASSETS"
echo "════════════════════════════════════════════════════════════════"
echo -e "${NC}"

# Verificar variáveis de ambiente
check_env() {
    local missing=0
    
    if [ -z "$JIRA_USER" ]; then
        echo -e "${RED}✗ JIRA_USER não definido${NC}"
        missing=1
    else
        echo -e "${GREEN}✓ JIRA_USER: $JIRA_USER${NC}"
    fi
    
    if [ -z "$JIRA_PASSWORD" ]; then
        echo -e "${RED}✗ JIRA_PASSWORD não definido${NC}"
        missing=1
    else
        echo -e "${GREEN}✓ JIRA_PASSWORD: ****${NC}"
    fi
    
    if [ $missing -eq 1 ]; then
        echo ""
        echo -e "${YELLOW}Configure as variáveis:${NC}"
        echo "  export JIRA_USER='JIRA_INT_HOT@claro.com.br'"
        echo "  export JIRA_PASSWORD='OeE5j85nFsjnrmDC4BDt77E1'"
        exit 1
    fi
}

# Verificar service account
check_gcp_auth() {
    echo ""
    echo -e "${BLUE}Verificando autenticação GCP...${NC}"
    
    SA_FILE="$ANSIBLE_DIR/files/service_account.json"
    if [ -f "$SA_FILE" ]; then
        echo -e "${GREEN}✓ Service account encontrado${NC}"
        gcloud auth activate-service-account --key-file="$SA_FILE" 2>/dev/null || true
    else
        echo -e "${YELLOW}⚠ Service account não encontrado em: $SA_FILE${NC}"
        echo "  Usando autenticação atual do gcloud"
    fi
    
    # Verificar autenticação
    if gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | head -1; then
        echo -e "${GREEN}✓ Autenticado no GCP${NC}"
    else
        echo -e "${RED}✗ Não autenticado no GCP${NC}"
        exit 1
    fi
}

# Menu interativo
interactive_mode() {
    echo ""
    echo -e "${BLUE}Modo interativo - informe os dados da VM:${NC}"
    echo ""
    
    read -p "Nome da instância: " INSTANCE_NAME
    read -p "Zona (ex: southamerica-east1-c): " ZONE
    read -p "Projeto GCP: " PROJECT
    
    if [ -z "$INSTANCE_NAME" ] || [ -z "$ZONE" ] || [ -z "$PROJECT" ]; then
        echo -e "${RED}Todos os campos são obrigatórios!${NC}"
        exit 1
    fi
}

# Função principal de teste
run_test() {
    local instance=$1
    local zone=$2
    local project=$3
    local mode=${4:-"dry-run"}
    
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}Testando: $instance ($zone) - Projeto: $project${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    
    # Passo 1: Verificar se a VM existe no GCP
    echo ""
    echo -e "${YELLOW}Passo 1: Verificando VM no GCP...${NC}"
    if gcloud compute instances describe "$instance" --zone="$zone" --project="$project" --format="value(name)" 2>/dev/null; then
        echo -e "${GREEN}✓ VM encontrada no GCP${NC}"
    else
        echo -e "${RED}✗ VM não encontrada no GCP${NC}"
        exit 1
    fi
    
    # Passo 2: Buscar detalhes da VM
    echo ""
    echo -e "${YELLOW}Passo 2: Coletando detalhes da VM...${NC}"
    
    INSTANCE_JSON=$(gcloud compute instances describe "$instance" \
        --zone="$zone" \
        --project="$project" \
        --format=json)
    
    # Extrair machine type
    MACHINE_TYPE=$(echo "$INSTANCE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['machineType'].split('/')[-1])")
    echo "  Machine Type: $MACHINE_TYPE"
    
    # Buscar detalhes do machine type
    MACHINE_TYPE_JSON=$(gcloud compute machine-types describe "$MACHINE_TYPE" \
        --zone="$zone" \
        --project="$project" \
        --format=json 2>/dev/null || echo "{}")
    
    # Passo 3: Testar transformação
    echo ""
    echo -e "${YELLOW}Passo 3: Testando transformação GCP → cloud_data...${NC}"
    
    cd "$ANSIBLE_DIR"
    
    # Criar arquivo temporário com dados
    TEMP_VARS=$(mktemp)
    cat > "$TEMP_VARS" << EOF
sample_instance: $INSTANCE_JSON
sample_machine_type: $MACHINE_TYPE_JSON
EOF
    
    ansible-playbook playbooks/test_transform.yml -e "@$TEMP_VARS" 2>&1 | tail -50
    
    rm -f "$TEMP_VARS"
    
    # Passo 4: Verificar se existe no CMDB
    echo ""
    echo -e "${YELLOW}Passo 4: Verificando se existe no CMDB...${NC}"
    
    CMDB_CHECK=$(curl -s -u "$JIRA_USER:$JIRA_PASSWORD" \
        -H "Content-Type: application/json" \
        -X POST \
        "https://api.atlassian.com/jsm/insight/workspace/76827f8b-4d96-46a6-abf2-f592d6b4b2d9/v1/object/aql?maxResults=1" \
        -d "{\"qlQuery\": \"objectTypeId = 121 AND Name = \\\"$instance\\\"\"}" 2>/dev/null || echo '{"total":0}')
    
    TOTAL=$(echo "$CMDB_CHECK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total', 0))" 2>/dev/null || echo "0")
    
    if [ "$TOTAL" -gt 0 ]; then
        echo -e "${YELLOW}⚠ Servidor já existe no CMDB${NC}"
        ACTION="atualizar"
    else
        echo -e "${GREEN}✓ Servidor NÃO existe no CMDB - será criado${NC}"
        ACTION="criar"
    fi
    
    # Passo 5: Executar sincronização (se não for dry-run)
    echo ""
    if [ "$mode" == "execute" ]; then
        echo -e "${YELLOW}Passo 5: Executando sincronização...${NC}"
        
        ansible-playbook playbooks/sync_single_instance.yml \
            -e "instance_name=$instance" \
            -e "zone=$zone" \
            -e "project=$project" \
            -v
        
        echo ""
        echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}✓ Sincronização concluída!${NC}"
        echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
    else
        echo -e "${YELLOW}Passo 5: [DRY-RUN] Sincronização não executada${NC}"
        echo ""
        echo -e "${BLUE}Para executar a sincronização real, rode:${NC}"
        echo ""
        echo "  $0 $instance $zone $project --execute"
        echo ""
        echo "  ou via ansible-playbook:"
        echo ""
        echo "  ansible-playbook playbooks/sync_single_instance.yml \\"
        echo "    -e \"instance_name=$instance\" \\"
        echo "    -e \"zone=$zone\" \\"
        echo "    -e \"project=$project\""
    fi
}

# Main
main() {
    check_env
    check_gcp_auth
    
    # Parâmetros
    INSTANCE_NAME=${1:-""}
    ZONE=${2:-""}
    PROJECT=${3:-""}
    MODE=${4:-"dry-run"}
    
    # Se --execute foi passado como 4º parâmetro
    if [ "$MODE" == "--execute" ]; then
        MODE="execute"
    fi
    
    # Se não passou parâmetros, modo interativo
    if [ -z "$INSTANCE_NAME" ]; then
        interactive_mode
    fi
    
    run_test "$INSTANCE_NAME" "$ZONE" "$PROJECT" "$MODE"
}

main "$@"
