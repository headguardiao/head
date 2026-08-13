FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --omit=dev

COPY src ./src

ENV NODE_ENV=production
EXPOSE 3000

# Alpine's node image ships a non-root "node" user; the app is stateless
# (no local writes), so it can run without root the whole time.
USER node

CMD ["node", "src/index.js"]
