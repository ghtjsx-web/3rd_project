FROM node:20-alpine

WORKDIR /app

ENV PORT=3000 \
    HOSTNAME="0.0.0.0"

COPY package.json ./
# devDependencies(tailwindcss 등) 포함 설치
RUN npm install

COPY . .

# Next.js 빌드 시점에 환경변수 전달 (NEXT_PUBLIC_API_URL 단일화)
# 기본값으로 Onpod 백엔드 주소 설정 (빌드 시점에 번들에 확실히 포함)
ARG NEXT_PUBLIC_API_URL="https://figindex-api.onpod.ai"
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build

ENV NODE_ENV=production

EXPOSE 3000

CMD ["sh", "-c", "npm run start -- -p ${PORT:-3000}"]
