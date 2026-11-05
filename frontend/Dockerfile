# Frontend React/Vite — 確定申告 2026
# Build estatico servido por Vite preview en :5200.
FROM node:22-alpine AS build

WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM node:22-alpine AS serve
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY --from=build /app/package.json ./package.json
RUN npm install -g vite@6

EXPOSE 5200
CMD ["vite", "preview", "--host", "--port", "5200"]
