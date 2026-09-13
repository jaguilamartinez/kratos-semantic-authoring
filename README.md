# Kratos Semantic Authoring

Primer prototipo para ejecutar un caso de Kratos mediante un worker HTTP. El caso actual es `test_model_3d.gid`, exportado desde GiD.

El worker solo acepta este caso y ejecuta un cálculo cada vez. La API principal y la interfaz se añadirán en los siguientes incrementos.

## Levantar el worker

Se necesita Docker con Compose:

```bash
docker compose up --build
```

El servicio queda disponible en `http://localhost:8001`.

```bash
curl http://localhost:8001/health
curl -X POST http://localhost:8001/runs
```

`POST /runs` mantiene la conexión abierta hasta que termina Kratos. Cada ejecución crea una carpeta en `artifacts/` con los logs, las salidas GiD y VTK, y un `summary.json`. Esta carpeta no se versiona.

El resultado se puede consultar de nuevo usando el identificador devuelto por el `POST`:

```bash
curl http://localhost:8001/runs/<run_id>
```

La imagen usa Python 3.12 y Kratos Structural Mechanics 10.4.3 para Linux `amd64`. En un Mac con Apple Silicon, Docker ejecuta la imagen mediante emulación.

Para ejecutar el runner directamente, sin levantar el servidor:

```bash
docker compose run --rm kratos-worker python /app/run_case.py
```

## Pruebas

```bash
python3 -m unittest discover -s tests
```

Estas pruebas comprueban que los archivos del caso siguen presentes y que no han cambiado sus materiales, grupos, cargas o configuración del solver.

## Estructura

- `cases/test_model_3d.gid/`: proyecto GiD original.
- `worker/app.py`: endpoints HTTP del worker.
- `worker/run_case.py`: prepara un directorio temporal, ejecuta Kratos y recoge los resultados.
- `tests/`: comprobaciones básicas del caso de referencia.
- `artifacts/`: resultados locales de cada ejecución.

La especificación de arquitectura está en `docs/private/`. Ese directorio se mantiene fuera de Git.
