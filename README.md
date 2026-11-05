# 確定申告 — aplicación de preparación

Aplicación local para organizar ingresos, gastos y borradores de 確定申告. Los datos de demostración son sintéticos.

## Limitaciones

- Software beta: los cálculos deben verificarse con las fuentes oficiales y las circunstancias individuales.
- El generador `.xtx` de 2025 pasa las comprobaciones XSD con datos sintéticos. La descarga permanece bloqueada hasta verificar la importación y completar los casos fiscales aplicables. La exportación oficial de 2026 sigue bloqueada: las especificaciones definitivas aún están pendientes.
- La autenticación está desactivada por defecto. Ejecute la aplicación solo en un equipo de confianza y no la exponga a Internet sin controles de acceso y revisión de seguridad. El OCR externo requiere configuración y consentimiento.

## Desarrollo local (SQLite)

1. En `backend`, cree un entorno virtual Python 3.12 e instale `pip install -e ".[dev]"`.
2. Cree `backend/.env` con `DATABASE_URL=sqlite:///./data.db`. Es un archivo local que no debe compartirse.
3. Ejecute `alembic upgrade head` y después `uvicorn app.main:app --host 127.0.0.1 --port 8200`.
4. En `frontend`, con Node 22, ejecute `npm ci` y `npm run dev`. Abra `http://127.0.0.1:5200`.

Los archivos de evidencia y declaraciones se guardan en `backend/data/`; mantenga copias de seguridad privadas. No utilice el seed de desarrollo con datos reales.

Verificación: backend `ruff check app tests`, `mypy app`, `pytest -q`; frontend `npm run lint`, `npm run typecheck`, `npm run test:run`, `npm run build`.

## Docker (proyecto local aislado)

Ejecute `docker compose up -d --build` y, en una instalación nueva, `docker compose exec backend alembic upgrade head`. Abra `http://127.0.0.1:5200`. Los documentos se guardan en el volumen `kakutei_appdata` y la base de datos en `kakutei_pgdata`; haga una copia de seguridad antes de actualizar una base existente. No ejecute `docker compose down -v` si necesita conservarlos.
