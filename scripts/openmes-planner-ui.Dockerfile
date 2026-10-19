# Build only UI assets from the existing local OpenMES image. No database steps.
FROM a4s-openmes-backend AS planner-ui
COPY packages/ /var/www/packages/
COPY backend/resources/js/Pages/admin/schedule/planner/views.jsx /var/www/html/resources/js/Pages/admin/schedule/planner/views.jsx
RUN npm ci --no-audit --no-fund && npm run build
