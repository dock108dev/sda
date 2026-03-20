FROM node:25.8-alpine AS base

# Install pnpm.
# Corepack signature verification has intermittently failed in CI/buildkit environments;
# install pnpm directly via npm to avoid keyid verification issues.
RUN npm install -g pnpm@9

WORKDIR /app

FROM base AS deps

# Copy workspace config and all package.json files
# Note: this repo does not commit pnpm-lock.yaml, so we cannot use --frozen-lockfile.
COPY pnpm-workspace.yaml package.json ./
COPY web/package.json ./web/
COPY packages/js-core/package.json ./packages/js-core/
COPY packages/ui/package.json ./packages/ui/
COPY packages/ui-kit/package.json ./packages/ui-kit/

# Install dependencies (will create a lockfile inside the image)
RUN pnpm install

FROM deps AS build

# These are needed at build time so Next can inline NEXT_PUBLIC_* into the browser bundle.
ARG NEXT_PUBLIC_SPORTS_API_URL=http://localhost:8000
ARG SPORTS_API_INTERNAL_URL=http://api:8000

ENV NEXT_PUBLIC_SPORTS_API_URL=$NEXT_PUBLIC_SPORTS_API_URL \
    SPORTS_API_INTERNAL_URL=$SPORTS_API_INTERNAL_URL

# Copy only source files from packages (NOT the entire directory, which would overwrite
# pnpm's node_modules symlinks created during the deps stage)
COPY packages/js-core/src ./packages/js-core/src
COPY packages/js-core/tsconfig.json ./packages/js-core/
COPY packages/ui/src ./packages/ui/src
COPY packages/ui/tsconfig.json ./packages/ui/
COPY packages/ui-kit/src ./packages/ui-kit/src
COPY packages/ui-kit/tsconfig.json ./packages/ui-kit/

# Copy web source files
COPY web/tsconfig.json web/next.config.ts web/next-env.d.ts ./web/
COPY web/src ./web/src
COPY web/public ./web/public

WORKDIR /app/web

# React 19 in this repo ships JS but no bundled `.d.ts`. TypeScript (with Next's defaults)
# expects `react` / `react-dom` to expose types via `package.json` `types` and/or `exports` conditions.
# Bridge that gap by copying DefinitelyTyped declarations into the installed packages AND patching their
# `package.json` to advertise the types (container-only; does not affect local dev).
RUN node -e "const fs=require('fs'); const path=require('path'); const pnpmDir=path.join('/app','node_modules','.pnpm'); const reactTypesDir=path.dirname(require.resolve('@types/react/package.json')); const reactDomTypesDir=path.dirname(require.resolve('@types/react-dom/package.json')); const patchJson=(p,mut)=>{const pkg=JSON.parse(fs.readFileSync(p,'utf8')); mut(pkg); fs.writeFileSync(p, JSON.stringify(pkg,null,2));}; const patchReact=(dir)=>{const pkgJson=path.join(dir,'package.json'); if(!fs.existsSync(pkgJson)) return; for(const f of ['index.d.ts','jsx-runtime.d.ts','jsx-dev-runtime.d.ts']) fs.copyFileSync(path.join(reactTypesDir,f), path.join(dir,f)); patchJson(pkgJson,(pkg)=>{pkg.types='./index.d.ts'; if(pkg.exports&&pkg.exports['.']&&typeof pkg.exports['.']==='object') pkg.exports['.'].types='./index.d.ts'; if(pkg.exports&&pkg.exports['./jsx-runtime']&&typeof pkg.exports['./jsx-runtime']==='object') pkg.exports['./jsx-runtime'].types='./jsx-runtime.d.ts'; if(pkg.exports&&pkg.exports['./jsx-dev-runtime']&&typeof pkg.exports['./jsx-dev-runtime']==='object') pkg.exports['./jsx-dev-runtime'].types='./jsx-dev-runtime.d.ts';});}; const patchReactDom=(dir)=>{const pkgJson=path.join(dir,'package.json'); if(!fs.existsSync(pkgJson)) return; fs.copyFileSync(path.join(reactDomTypesDir,'index.d.ts'), path.join(dir,'index.d.ts')); patchJson(pkgJson,(pkg)=>{pkg.types='./index.d.ts'; if(pkg.exports&&pkg.exports['.']&&typeof pkg.exports['.']==='object') pkg.exports['.'].types='./index.d.ts';});}; for(const entry of fs.readdirSync(pnpmDir)) { if(entry.startsWith('react@')) patchReact(path.join(pnpmDir, entry, 'node_modules', 'react')); if(entry.startsWith('react-dom@')) patchReactDom(path.join(pnpmDir, entry, 'node_modules', 'react-dom')); }"

RUN pnpm run build

FROM base AS runner

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000

# Create non-root user BEFORE any file operations. All subsequent COPY
# uses --chown and pnpm install runs as appuser, so no chown -R layer
# is needed. A separate chown -R layer on pnpm's deeply nested
# node_modules paths caused overlayfs extraction failures on pull
# (containerd Lchown "no such file or directory" on long .pnpm paths).
RUN addgroup -S appgroup \
    && adduser -S appuser -G appgroup \
    && mkdir -p /app && chown appuser:appgroup /app

WORKDIR /app

# Copy workspace config (see note above about pnpm-lock.yaml)
COPY --chown=appuser:appgroup pnpm-workspace.yaml package.json ./
COPY --chown=appuser:appgroup web/package.json ./web/
COPY --chown=appuser:appgroup packages/js-core/package.json ./packages/js-core/
COPY --chown=appuser:appgroup packages/ui/package.json ./packages/ui/
COPY --chown=appuser:appgroup packages/ui-kit/package.json ./packages/ui-kit/

# Install production deps as appuser — avoids root-owned node_modules
# and eliminates the need for a chown -R layer.
USER appuser
RUN pnpm install --prod

# Copy built assets
COPY --chown=appuser:appgroup --from=build /app/web/.next ./web/.next
COPY --chown=appuser:appgroup --from=build /app/web/public ./web/public

# Copy packages source (needed at runtime for Next.js to resolve workspace imports)
COPY --chown=appuser:appgroup packages/js-core/src ./packages/js-core/src
COPY --chown=appuser:appgroup packages/ui/src ./packages/ui/src
COPY --chown=appuser:appgroup packages/ui-kit/src ./packages/ui-kit/src

WORKDIR /app/web

EXPOSE 3000

CMD ["pnpm", "start"]
