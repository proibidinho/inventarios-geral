# Sync CMDB - Servidores On-Premise (VMware)

Integração que coleta `ansible_facts` de servidores recém-provisionados e cria
o objeto **Servidor** correspondente no **Jira Assets (CMDB)** do time de Infra.

> Escopo: servidores **novos** em VMware (Linux ou Windows). Não atualiza
> servidores existentes — apenas cria.

---

## 1. Objetivo

- Eliminar o cadastro manual de servidores no CMDB após o provisionamento.
- Preencher automaticamente: nome, FQDN, SO, versão do SO, RAM, vCPU, disco,
  interfaces de rede, datacenter, ambiente, modelo, fornecedor e status.
- Servir como **última etapa de um Workflow Job Template** no AAP, após o
  provisionamento das VMs.

---

## 2. Estrutura

```
.
├── ansible.cfg
├── group_vars/
│   └── all.yml                              # TODOS os mappings/IDs do CMDB
├── playbooks/
│   └── sync_facts_cmdb.yml                  # ENTRY POINT (único)
└── roles/
    ├── inventory/
    │   └── tasks/main.yml                   # constroi grupo dinamico (aai / windows_alvo)
    └── cmdb_sync/
        └── tasks/
            ├── main.yml                     # categoriza facts + monta payload + POST
            └── manage_network_interface.yml # cria/busca NICs no CMDB
```

---

## 3. Variáveis do Survey (Workflow Job Template)

| Variável | Tipo | Valores aceitos | Exemplo |
|---|---|---|---|
| `vms_provisionadas` | lista de `{hostname, ip}` | obrigatório | ver abaixo |
| `operation_system_name` | string | `Oracle_Linux_8`, `Oracle_Linux_9`, `RHEL_8`, `RHEL_9`, `Windows_Server_2022`, `Windows_Server_2025` | `RHEL_9` |
| `datacenter_name` | string | `Campinas`, `Lapa`, `Mackenzie` | `Lapa` |
| `environment_name` | string | `Certificação`, `Desenvolvimento`, `Homologação`, `Legado`, `OPDK`, `Pré-Produção`, `Produção`, `Produção Disaster Recovery`, `Produção Nextel`, `Projeto`, `SaaS`, `SaaS-Eng`, `Secure Agent`, `Teste`, `Treinamento` | `Desenvolvimento` |

### Exemplo de `vms_provisionadas`

```yaml
vms_provisionadas:
  - { hostname: CBC2AM71072, ip: 10.54.81.228 }
  - { hostname: CBC2AM89230, ip: 10.54.81.225 }
```

---

## 4. Pré-requisitos

### Variáveis de ambiente (Job Template → Credential do tipo *Vault*)
- `JIRA_USER`
- `JIRA_PASSWORD`

### Collections Ansible
- `ansible.windows`  *(WinRM)*
- `cyberark.pas`     *(busca de senha Windows)*

### Conectividade
- **Linux**: SSH 22 do execution node até a VM, autenticação por **chave de
  confiança** (`linux_user_default: root`).
- **Windows**: WinRM 5985 + NTLM, credencial recuperada do **CyberArk**
  (`Safe=APP_Ansible;UserName=OPS_CRK_API_AAPWIN`).
- **Jira Assets** via proxy `10.54.24.184:3128`.

---

## 5. Configuração no AAP

### 5.1 Job Template `cmdb-sync` (1 só)

| Campo | Valor |
|---|---|
| Inventory | qualquer (o playbook constrói o inventário dinâmico em runtime) |
| Playbook | `playbooks/sync_facts_cmdb.yml` |
| Credentials | *vazio* |
| **Prompt on Launch — Credentials** | ✅ |
| **Prompt on Launch — Instance Groups** | ✅ |
| **Prompt on Launch — Variables** | ✅ |

### 5.2 Workflow Job Template

1. Crie o **survey** com as 4 variáveis da seção 3.
2. No Visual Editor, adicione **3 nós paralelos** apontando para o JT
   `cmdb-sync` — um por DC, sobrescrevendo Instance Group e Credentials:

| Nó | Instance Group | Credentials |
|---|---|---|
| `cmdb-sync-campinas` | `ig-campinas` | credencial(is) de Campinas |
| `cmdb-sync-lapa` | `ig-lapa` | credencial(is) de Lapa |
| `cmdb-sync-mackenzie` | `ig-mackenzie` | credencial(is) de Mackenzie |

3. Como o AAP 2.5 não tem *conditional node*, encadeie em série usando
   **"On Failure"** entre os nós — o nó certo executa, o errado falha rápido
   no `assert`. Ou utilize o filtro manual no survey/playbook.

### 5.3 Quando entrar um novo DC
- Cria Instance Group + Credentials.
- Acrescenta nó no workflow.
- Acrescenta entrada em `cmdb.datacenter_ids` (`group_vars/all.yml`).
- Acrescenta o valor no survey de `datacenter_name`.

---

## 6. Mapeamento dos campos preenchidos

| Campo CMDB | ID atributo | Tipo | Origem |
|---|---|---|---|
| Name | 1104 | Text | `ansible_hostname` |
| FQDN | 3343 | Text | `ansible_fqdn` |
| Sistema Operacional | 3358 | Reference | `operation_system_name` → `Linux`/`Windows` |
| Versão SO | 3471 | Reference | `operation_system_name` (Oracle_Linux_9 → ID 3062950, etc.) |
| Memória RAM | 6840 | Integer | `ansible_memtotal_mb` |
| CPU Count | 3359 | Text | `ansible_processor_vcpus` |
| Capacidade do Disco | 3613 | Text | soma de `ansible_mounts[].size_total` (Linux apenas) |
| Interface de Rede | 3528 | Reference list | IPs filtrados (cria objeto NIC se não existir) |
| Tipo de Infraestrutura | 9948 | Reference | `MAQUINA VIRTUAL` quando `ansible_virtualization_role == guest` |
| Datacenter | 3296 | Reference | `datacenter_name` |
| **Ambiente** | 1922 | Reference | `environment_name` |
| **Modelo de Servidor** | 15656 | Reference | fixo `VMWare` (id 3230997) |
| **Fornecedor** | 6829 | Text | derivado de `operation_system_name` (`Oracle`, `Red Hat`, `Microsoft`) |
| Status | 2957 | Status | fixo `Em uso` |
| Status Discovery | 3053 | Status | fixo `Running` |
| Last User | 3357 | Text | fixo `Ansible` |
| SOX | 9647 | Boolean | fixo `false` |
| IPE | 9648 | Boolean | fixo `false` |
| Disaster Recovery | 10677 | Boolean | fixo `false` |

---

## 7. Como adicionar / manter

Toda manutenção fica concentrada em **`group_vars/all.yml`**.

### Novo Datacenter
```yaml
cmdb:
  datacenter_ids:
    "Novo DC": 0000000   # ID do objeto no CMDB
```

### Novo Sistema Operacional (3 lugares)
```yaml
cmdb:
  versao_so_ids:
    RHEL_10: 0000000   # ID do objeto "Red Hat Enterprise Linux 10..."
  so_categoria:
    RHEL_10: Linux
  fornecedor_por_so:
    RHEL_10: "Red Hat"
```

E acrescente o valor `RHEL_10` na lista de opções do survey.

### Novo Ambiente
```yaml
cmdb:
  ambiente_ids:
    "Novo Ambiente": 0000000
```

E na lista de validação do `environment_name` no playbook
(`playbooks/sync_facts_cmdb.yml`).

### Mudar hypervisor (ex.: Hyper-V no lugar de VMware)
- Cria o objeto correspondente no CMDB (campo Modelo de Servidor / ref 406).
- Em `group_vars/all.yml` → `cmdb.modelo_servidor_ids`, acrescenta a entrada.
- Em `roles/cmdb_sync/tasks/main.yml`, troca o valor fixo `'VMWare'` pelo nome
  do novo modelo. Ou transforma em variável (ex.: `hypervisor_name`) populada
  pelo survey.

### Ativar CyberArk no Linux
Quando o time CyberArk liberar o usuário, basta trocar `use_cyberark: true`
para os dois SOs e adicionar a busca CyberArk Linux na Fase 1 do playbook
(`sync_facts_cmdb.yml`), espelhando o bloco do Windows. O `linux_user_default`
em `group_vars/all.yml` pode ser sobrescrito por `host_ansible_user`.

### Ativar "Grupo Solucionador - Infra" (campo 7274)
1. Peça ao time CMDB os `referencedType` das opções `Windows` e `Infracloud`.
2. Em `group_vars/all.yml`, crie o bloco `grupo_solucionador_ids` e o
   `cmdb.attr_ids.grupo_solucionador`.
3. Em `roles/cmdb_sync/tasks/main.yml`, acrescente a linha em `attrs_raw`.

---

## 8. Pendências / TODOs conhecidos

| Campo CMDB | Status | Pendência |
|---|---|---|
| Filesystems (3371) | ❌ não preenche | Time CMDB vai converter de Reference para Text |
| Storage Devices (3395) | ❌ não preenche | 500+ opções (Reference) — manutenção inviável |
| CPU (3527) | ❌ não preenche | 500+ opções (Reference) — manutenção inviável |
| Grupo Solucionador (7274) | ⚠️ pronto, comentado | Falta `referencedType` das opções no CMDB |
| Owner (3381) | ⚠️ depende de input | Não vem nas tags/survey — virá em fase futura |
| Sistema (9219) | ⚠️ depende de input | Idem |
| VCenter (8742) | ⚠️ depende de input | Opções do CMDB não correspondem a regiões/clusters Azure/VMware atuais |
| IaC | ⚠️ aguarda CMDB | Atributo ainda **não existe** no CMDB |
| CyberArk Linux | ⚠️ comentado | Aguardando liberação do usuário CyberArk Linux |

---

## 9. Troubleshooting

### Campo apareceu vazio no CMDB
1. Confira o **debug** da execução (`DEBUG - dados categorizados`) — se o valor
   está vazio na origem (`ansible_*`), o atributo é omitido do payload.
2. Para campos `Reference`: confira se o valor recebido (ex.: `Desenvolvimento`)
   está em `group_vars/all.yml`. Match é **case-sensitive**.
3. Verifique o **payload final** no debug (`DEBUG - payload final`) — se o
   atributo estiver lá com `value` correto e mesmo assim o campo ficar vazio,
   é problema do lado do Jira Assets (verificar permissão do usuário API).

### Falha de autenticação na Fase 2
- **Linux**: chave SSH não propagada no template da VM. Verificar com a equipe
  de provisioning. Comando útil:
  `ssh root@<ip> -o BatchMode=yes -o ConnectTimeout=5 echo OK`
- **Windows**: CyberArk retornou erro. Conferir o log da task `CyberArk Windows`.
  Senha em rotação? Conta deletada?

### `HTTP 401 Unauthorized` no Jira Assets
- `JIRA_USER` e/ou `JIRA_PASSWORD` (API Token) errados.
- Token expirou — gerar novo em
  `https://id.atlassian.com/manage-profile/security/api-tokens`.

### `HTTP 400 Bad Request` ao criar
- Algum `referencedType` no `group_vars/all.yml` está apontando pra um objeto
  que não existe mais (foi deletado / renomeado no CMDB).
- Reverificar o ID no dump do CMDB ou direto na UI.

### Servidor duplicado no CMDB
- Este playbook **sempre cria** (não busca/skip). Se for executado 2x para a
  mesma VM, criará 2 objetos. Cuidado em re-runs.

---

## 10. Execução manual (debug local)

```bash
export JIRA_USER='seu-email@claro.com.br'
export JIRA_PASSWORD='seu-api-token'

ansible-playbook playbooks/sync_facts_cmdb.yml \
  -e '{"vms_provisionadas":[{"hostname":"CBC2AM71072","ip":"10.54.81.228"}]}' \
  -e operation_system_name=RHEL_9 \
  -e datacenter_name=Lapa \
  -e environment_name=Desenvolvimento
```
