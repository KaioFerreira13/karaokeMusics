FROM node:20-alpine

WORKDIR /app

# Instala as dependências primeiro para aproveitar o cache de camadas do Docker
COPY package*.json ./

RUN npm install

# Copia o código-fonte da aplicação
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
