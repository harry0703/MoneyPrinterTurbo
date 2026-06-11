# Instalador DEMO — MoneyPrinterTurbo BR

> **© 2026 THM TECNOLOGIA** — autoria, engenharia e auditoria.
> Distribuído sob a licença MIT do repositório (ver [LICENSE](../LICENSE)), com
> **manutenção obrigatória do aviso de autoria** em todas as cópias.

## ⬇ Download

**[Instalar-MoneyPrinterTurbo-DEMO.bat](Instalar-MoneyPrinterTurbo-DEMO.bat)** —
clique no link → botão **Download raw file** → salve e dê **duplo clique**.

## O que a DEMO instala (tudo automático, em um clique)

1. **Python** — detecta ou instala sozinho (winget ou python.org), sem reiniciar
2. **O programa** — baixa direto do GitHub (sem precisar de Git)
3. **Dependências** — com barra de progresso e instrução clara
4. **Configuração DEMO** — interface em português, roteiros pelo provedor de IA
   gratuito, e a chave gratuita do Pexels pedida em uma janelinha
5. **Modo Aplicativo** — ícone na Área de Trabalho, tela de carregamento,
   janela própria (sem cara de navegador) e ícone na bandeja do sistema
6. **Abre o programa** ao final, pronto para gerar o primeiro vídeo

É retomável (rodar de novo continua de onde parou) e termina com o aplicativo
aberto na tela.

## Limitações da DEMO

- Roteiros apenas pelo provedor de IA gratuito (Pollinations)
- Painel de configurações avançadas bloqueado
- Sem acesso pelo iPhone/iPad
- Sem instalação assistida e sem suporte

## 💎 Ferramenta BR Completa

Inclui tudo da DEMO **mais**:

- **Todos os provedores de IA** liberados (OpenAI, Gemini, DeepSeek e outros)
- **Painel de configurações liberado**
- **Uso pelo iPhone/iPad em casa**: um clique no PC mostra um QR Code — a
  câmera do iPhone abre a ferramenta, que vira um app na tela de início
- **Uso pelo iPhone em qualquer lugar** (4G/5G): acesso remoto por túnel
  criptografado, configurado automaticamente
- **Instalação assistida** e configuração das suas chaves
- **Suporte direto da THM TECNOLOGIA**, em português

**Para obter a versão completa, entre em contato:**

### 💬 Telegram: [t.me/rdllmsu](https://t.me/rdllmsu)

## Auditoria e código-fonte

O `.bat` carrega o instalador real (PowerShell) embutido em Base64, decodificado
via `certutil` (nativo do Windows), com verificação de integridade. Os fontes
legíveis para auditoria estão em [`fontes/`](fontes/):

| Fonte | Papel |
|---|---|
| `instalador-demo.ps1` | Instalador DEMO (6 passos) |
| `MoneyPrinterTurboApp.ps1` | Modo Aplicativo: splash, servidor oculto, janela própria, bandeja |
| `MoneyPrinterTurboApp.vbs` | Inicialização invisível (sem janela preta) |

Nenhuma etapa exige privilégios de administrador. As chaves digitadas ficam
apenas no `config.toml` local do seu computador, e nada é exposto à internet.
