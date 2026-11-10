FROM node:20-alpine

WORKDIR /app

ENV PORT=3000 \
    HOSTNAME="0.0.0.0"

COPY package.json ./
# devDependencies(tailwindcss 등) 포함 설치
RUN npm install

COPY . .

# Next.js 빌드 시점에 환경변수 전달
ARG NEXT_PUBLIC_BACKEND_URL
ENV NEXT_PUBLIC_BACKEND_URL=${NEXT_PUBLIC_BACKEND_URL}

RUN npm run build

ENV NODE_ENV=production

EXPOSE 3000

CMD ["sh", "-c", "npm run start -- -p ${PORT:-3000}"]
