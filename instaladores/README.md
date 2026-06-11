# Instaladores Oficiais — MoneyPrinterTurbo

> **© 2026 THM TECNOLOGIA** — autoria, engenharia e auditoria dos instaladores.
> Estes arquivos são distribuídos sob a **mesma licença MIT** do repositório
> (ver [LICENSE](../LICENSE)). Conforme a licença MIT, **a manutenção do aviso
> de copyright/autoria da THM TECNOLOGIA é obrigatória** em todas as cópias e
> redistribuições.

Pacote de instalação **tudo-em-um** para pessoas leigas: um download, um
duplo clique, zero configuração manual. Cada instalador carrega o aviso de
autoria da THM TECNOLOGIA no cabeçalho e dentro do código embutido.

## Downloads (Windows)

| Arquivo | O que faz |
|---|---|
| **[Instalar-MoneyPrinterTurbo-TUDO-EM-UM.bat](Instalar-MoneyPrinterTurbo-TUDO-EM-UM.bat)** | Instalação completa em fluxo único: instala o Python sozinho (winget ou python.org, sem reiniciar), baixa o programa (sem Git), instala dependências, pede as chaves em janelinhas (abre a página do Pexels sozinho), cria o Modo Aplicativo + ícone na Área de Trabalho e termina com a interface aberta. Retomável e idempotente. |
| **[Conectar-iPhone-UM-CLIQUE.bat](Conectar-iPhone-UM-CLIQUE.bat)** | iPhone/iPad na mesma Wi-Fi: autoriza o firewall sozinho (1 clique de UAC), liga o servidor invisível e mostra um QR Code na tela — aponte a câmera do iPhone e toque em "Adicionar à Tela de Início". Ícone azul na bandeja com opções. |
| **[iPhone-Em-Qualquer-Lugar-TAILSCALE.bat](iPhone-Em-Qualquer-Lugar-TAILSCALE.bat)** | iPhone em qualquer lugar (4G/5G): instala o Tailscale sozinho, abre o login (Google/Apple/Microsoft), libera o firewall e mostra 2 QR Codes — um para instalar o app Tailscale no iPhone (primeira vez) e outro para acessar a interface de qualquer rede, por túnel criptografado. Ícone roxo na bandeja. |

**Como baixar:** clique no arquivo acima → botão **Raw** / **Download raw file** → salve e dê duplo clique.

## Ordem de uso

1. `Instalar-MoneyPrinterTurbo-TUDO-EM-UM.bat` — sempre primeiro (instala tudo).
2. `Conectar-iPhone-UM-CLIQUE.bat` — opcional, para usar pelo celular em casa.
3. `iPhone-Em-Qualquer-Lugar-TAILSCALE.bat` — opcional, para usar fora de casa.

## Auditoria e código-fonte

Os `.bat` carregam o instalador real (PowerShell) embutido em Base64,
decodificado via `certutil` (nativo do Windows). Para auditoria, os
códigos-fonte legíveis estão em [`fontes/`](fontes/):

| Fonte | Papel |
|---|---|
| `instalador-completo.ps1` | Instalador principal (6 passos; embute os dois arquivos do app) |
| `MoneyPrinterTurboApp.ps1` | Modo Aplicativo: splash, servidor oculto, janela própria, bandeja |
| `MoneyPrinterTurboApp.vbs` | Bootstrapper invisível (sem janela preta) |
| `ConectariPhone.ps1` | Conector Wi-Fi local com QR Code e firewall automático |
| `AcessoRemotoiPhone.ps1` | Acesso remoto via Tailscale com QR Codes e login assistido |

Nenhum instalador requer privilégios de administrador, exceto as etapas de
firewall/Tailscale, que pedem a confirmação padrão do Windows (UAC) — a única
"autorização" que o sistema operacional não permite automatizar, por segurança.

## Segurança e privacidade

- **QR Codes gerados 100% localmente** (biblioteca qrcode.js, MIT, embutida):
  nenhum endereço privado é enviado a serviços externos.
- Nada é exposto à internet pública: o acesso local fica restrito à sua rede
  Wi-Fi (regra de firewall escopada ao executável do programa), e o acesso
  remoto só aceita conexões vindas da faixa do Tailscale (100.64.0.0/10),
  por túnel criptografado.
- As chaves digitadas ficam apenas no `config.toml` local do seu computador.
- Encerrar tudo: botão direito no ícone da bandeja → **Encerrar**.
