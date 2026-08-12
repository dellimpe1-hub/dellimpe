# Implantação da API

O site estático funciona no GitHub Pages. O formulário com anexos precisa da API Flask hospedada separadamente.

## Neon

1. Revogue a senha exposta anteriormente e gere uma nova no Neon.
2. Copie a nova connection string pooled.
3. Nunca grave a connection string em arquivos do repositório.

## Render

1. No Render, crie um Blueprint usando este repositório.
2. No serviço `dellimpe-api`, defina `DATABASE_URL` como Secret com a nova connection string do Neon.
3. Aguarde o deploy e copie a URL pública, por exemplo `https://dellimpe-api.onrender.com`.
4. Em `api-config.js`, informe somente a URL pública da API e publique novamente o site.

As tabelas do Neon são criadas automaticamente na primeira inicialização da API.
