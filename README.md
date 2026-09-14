# Kratos Semantic Authoring

Prototipo de edición semántica para casos de Structural Mechanics en Kratos. La API construye el modelo canónico desde los archivos del caso y permite cambiar variables escalares de materiales y parámetros escalares de procesos. `test_model_3d.gid` es el caso de demostración, no un contrato del código.

El repositorio contiene tres servicios:

- `frontend`, una interfaz React para enviar prompts y explorar el modelo canónico.
- `authoring-api`, que mantiene el modelo canónico, interpreta una petición con un LLM y genera una revisión ejecutable.
- `kratos-worker`, que ejecuta el caso original o una revisión generada.

Los archivos GiD originales nunca se modifican. Cada cambio crea un bundle nuevo en `workspace/revisions/`, un directorio local que Git ignora.

## Arranque

Se necesita Docker con Compose. Para usar la edición en lenguaje natural, copia el archivo de entorno y añade una clave de OpenAI:

```bash
cp .env.example .env
```

Después levanta los servicios:

```bash
docker compose up --build
```

La interfaz queda en `http://localhost:3000`, la API de autoría en `http://localhost:8000` y el worker en `http://localhost:8001`.

```bash
curl http://localhost:8000/health
curl http://localhost:8000/case
curl http://localhost:8001/health
```

## Editar el caso

El campo `expected_revision` evita sobrescribir un cambio más reciente. Se obtiene con `GET /case`.

La interfaz permite enviar el prompt y representa el modelo actual como un grafo de materiales y procesos. Los nodos se pueden seleccionar y mover para ordenar la vista sin modificar el caso. Usa IBM Carbon para los componentes y `@xyflow/react` para el grafo; no contiene nombres ni reglas del caso de demostración.

La pestaña `Revisions` permite ejecutar en Kratos cualquiera de las revisiones creadas en el workspace y muestra el resumen de la última ejecución. Las revisiones son inmutables: ejecutarlas no cambia cuál es la revisión actual.

La ruta directa permite probar la operación determinista sin llamar al LLM:

```bash
curl -X POST http://localhost:8000/tools/apply-case-changes \
  -H 'Content-Type: application/json' \
  -d '{
    "expected_revision": 0,
    "material_changes": [
      {
        "model_part_name": "Structure.Volume3",
        "variable_name": "YOUNG_MODULUS",
        "value": 3500000000
      }
    ],
    "process_changes": []
  }'
```

Para recorrer el mismo camino mediante lenguaje natural:

```bash
curl -X POST http://localhost:8000/edits \
  -H 'Content-Type: application/json' \
  -d '{
    "expected_revision": 0,
    "prompt": "Cambia YOUNG_MODULUS de Volume3 a 3500000000 en las unidades actuales del modelo"
  }'
```

La respuesta incluye el diff semántico, la revisión y las llamadas de tool realizadas. El sistema de unidades del caso aún no está confirmado; por eso el LLM pregunta en vez de convertir valores expresados en Pa, GPa, N u otras unidades.

El prompt y el modelo canónico actual se envían a OpenAI. No se envían la geometría, la malla ni los archivos de Kratos.

## Ejecutar una revisión

El worker sigue aceptando un `POST` vacío para ejecutar el caso original:

```bash
curl -X POST http://localhost:8001/runs
```

Para ejecutar un bundle generado, indica su número de revisión:

```bash
curl -X POST http://localhost:8001/runs \
  -H 'Content-Type: application/json' \
  -d '{"revision": 1}'
```

Cada cálculo crea una carpeta en `artifacts/` con los logs, los archivos producidos por los output processes del caso y un `summary.json`. El resultado se puede consultar de nuevo con `GET /runs/<run_id>`.

## Pruebas

Con las dependencias de autoría instaladas:

```bash
python3 -m unittest discover -s tests
```

Las pruebas cubren el contrato del caso original, un segundo caso con nombres arbitrarios, las mutaciones, la compilación determinista y el flujo del agente con el modelo de pruebas del SDK. La llamada real al LLM queda fuera de la suite para que las pruebas no dependan de red ni consuman crédito.

## Estructura

- `authoring/`: lector del caso, modelo canónico, agente, compilador, persistencia y API de edición.
- `cases/test_model_3d.gid/`: proyecto GiD original, montado en solo lectura.
- `frontend/`: aplicación React, cliente HTTP y grafo del modelo canónico.
- `worker/`: API y runner de Kratos.
- `workspace/`: revisiones generadas localmente.
- `artifacts/`: resultados de las ejecuciones.
- `tests/`: pruebas del caso y de la autoría.

La especificación de arquitectura está en `docs/private/`. Ese directorio se mantiene fuera de Git. OpenAI Agents SDK gestiona el ciclo modelo/tool. MCP sigue aplazado y LangGraph se reconsiderará cuando el flujo necesite pausas y reanudación persistente.
