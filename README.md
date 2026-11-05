# 確定申告 — aplicación de preparación

Aplicación local para organizar ingresos, gastos y borradores de 確定申告. Los datos de demostración son sintéticos.

## Limitaciones

- Software beta: los cálculos deben verificarse con las fuentes oficiales y las circunstancias individuales.
- El archivo `.xtx` no cumple todavía el XSD oficial y no debe considerarse listo para presentar. La exportación oficial de 2026 permanece bloqueada mientras no se verifique su formato.
- La autenticación está desactivada por defecto. Ejecute la aplicación solo en un equipo de confianza y no la exponga a Internet sin controles de acceso y revisión de seguridad. El OCR externo requiere configuración y consentimiento.

## Desarrollo local (SQLite)

1. En `backend`, cree un entorno virtual Python 3.12 e instale `pip install -e ".[dev]"`.
2. Cree `backend/.env` con `DATABASE_URL=sqlite:///./data.db`. Es un archivo local que no debe compartirse.
3. Ejecute `alembic upgrade head` y después `uvicorn app.main:app --host 127.0.0.1 --port 8200`.
4. En `frontend`, con Node 22, ejecute `npm ci` y `npm run dev`. Abra `http://127.0.0.1:5200`.

Los archivos de evidencia y declaraciones se guardan en `backend/data/`; mantenga copias de seguridad privadas. No utilice el seed de desarrollo con datos reales.

Verificación: backend `ruff check app tests`, `mypy app`, `pytest -q`; frontend `npm run lint`, `npm run typecheck`, `npm run test:run`, `npm run build`. La configuración Docker incluida no ha sido validada para esta versión.
