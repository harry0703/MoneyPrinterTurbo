# Guia Rápido para Preguiçosos 😴 (MoneyPrinterTurbo)

Se você não quer ler o README inteiro e só quer colocar essa ferramenta para rodar o mais rápido possível, siga estes passos simples.

---

## Passo 1: O Atalho do Windows (Para quem usa Windows)
Se você está no Windows, não precisa instalar nada manualmente.
1. Baixe o pacote de inicialização rápida (One-Click) na página de [Releases do GitHub](https://github.com/harry0703/MoneyPrinterTurbo/releases/latest).
2. Descompacte o arquivo numa pasta (ex: `C:\MoneyPrinterTurbo`). **Atenção:** O caminho da pasta NÃO pode ter acentos, espaços ou caracteres especiais.
3. Dê duplo clique em `update.bat` para garantir que tem o código mais recente.
4. Dê duplo clique em `start.bat`. Pronto! O seu navegador vai abrir a interface sozinho.

---

## Passo 2: O Atalho do Docker (Para quem tem Docker)
Se você já tem o Docker instalado na sua máquina:
1. Copie o arquivo `config.example.toml` e salve como `config.toml`.
2. Rode o comando abaixo no seu terminal dentro da pasta do projeto:
   ```shell
   docker compose -f docker-compose.release.yml up
   ```
3. Abra o seu navegador e aceda a: `http://127.0.0.1:8501`

---

## Passo 3: O Atalho do Google Colab (Sem instalar nada no PC!)
Se você não quer instalar nada no seu computador e quer rodar tudo na nuvem gratuitamente:
1. Clique neste link para abrir no Google Colab: [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/harry0703/MoneyPrinterTurbo/blob/main/docs/MoneyPrinterTurbo.ipynb)
2. Siga os 3 passos simples dentro do notebook para rodar na nuvem e gerar o link público.

---

## Passo 4: Configurando as Chaves (Muito Importante)
Depois de abrir a página no navegador:
1. **Vídeos de Fundo:** Vá em "Configurações da Fonte do Vídeo" e selecione "Pexels" ou "Pixabay". Você precisará criar uma conta gratuita no [Pexels API](https://www.pexels.com/api/) ou [Pixabay API](https://pixabay.com/api/docs/) para obter a sua chave gratuita e colar na tela.
2. **Inteligência Artificial (Roteiro):** Vá em "Configurações do LLM", escolha o seu provedor (como OpenAI ou AIHubMix) e coloque a sua chave de API para que o robô consiga escrever os roteiros dos seus vídeos.
3. Clique em **Começar a Gerar Vídeo** e espere o seu vídeo ficar pronto para download!
