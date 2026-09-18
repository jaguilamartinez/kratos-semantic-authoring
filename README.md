# Kratos Semantic Authoring

Prototipo local para editar casos de Kratos Structural Mechanics desde un modelo canónico. El caso de referencia es `test_model_3d.gid`; sus archivos originales se montan en solo lectura.

El proyecto tiene tres servicios:

- `frontend`: React, Carbon y React Flow.
- `authoring-api`: modelo canónico, tools tipadas, borradores y revisiones.
- `kratos-worker`: preflight y ejecución en Kratos 10.4.3 para Linux/amd64.

## Arranque

Se necesita Docker con Compose:

```bash
cp .env.example .env
# añade OPENAI_API_KEY al fichero .env para habilitar los prompts
docker compose up --build
```

La interfaz queda en `http://localhost:3000`. Las APIs se publican en `8000` y `8001` para inspección local.

```bash
curl http://localhost:8000/health
curl http://localhost:8000/case
curl http://localhost:8001/health
```

## Flujo de edición

Un prompt siempre crea o actualiza un borrador. El borrador guarda la conversación y un changelog ordenado de cada actualización del modelo, por lo que los mensajes siguientes se interpretan sobre el mismo contexto y el diff permanece abierto hasta publicar. No modifica la revisión publicada.

1. `POST /edits` interpreta el prompt con OpenAI Agents SDK y devuelve un borrador persistido.
2. `POST /drafts/<id>/validate` valida referencias, cobertura y compilación; para el perfil ejecutable también ejecuta `Initialize`/`Check` de Kratos en un directorio temporal.
3. `POST /drafts/<id>/publish` publica una revisión inmutable sólo si el hash validado sigue siendo el actual y la revisión base no ha cambiado.

El cliente HTTP y la interfaz muestran el diff semántico y el diff de archivos. Si otro cambio publica una revisión mientras se edita, el borrador se conserva y se informa del conflicto.

## Modelo canónico

`ksa.structural-case/0.3` representa por separado:

- análisis, numerics y ejecución;
- modelo, regiones y referencias inmutables a mallas;
- preparación/modelers con su orden;
- materiales y asignaciones de propiedades;
- condiciones de contorno, cargas, condiciones iniciales y procesos auxiliares;
- outputs con su orden;
- extensiones nativas no conocidas.

Cada componente tiene un identificador estable, una capacidad del catálogo y los campos nativos restantes. El compilador genera `ProjectParameters.json`, el fichero de materiales y las mallas desde el canónico; no vuelve a leer una plantilla mutable para rellenar campos olvidados. Los campos desconocidos se conservan como `native-only` y no se ofrecen como edición semántica.

El catálogo actual está fijado a Kratos 10.4.3 y al perfil `structural-static-3d`. Cubre el caso base: importación MDPA, creación de elementos/condiciones, elasticidad lineal 3D, desplazamiento impuesto, fuerza puntual, tracción superficial, GiD y VTK. Dinámica, modal, presión e initial conditions quedan declarados para perfiles posteriores.

## API útil

```bash
# capacidades y tools que recibe el agente
curl http://localhost:8000/capabilities
curl http://localhost:8000/tools

# borrador determinista, sin LLM (sustituye el ID por uno de /case)
curl -X POST http://localhost:8000/tools/propose-case-changes \
  -H 'Content-Type: application/json' \
  -d '{"expected_revision":0,"commands":[{"type":"configure_numerics","max_iterations":12}]}'

# revisiones publicadas
curl http://localhost:8000/revisions
curl -X POST http://localhost:8001/runs \
  -H 'Content-Type: application/json' -d '{"revision":0}'
```

Las mallas y los ficheros de las revisiones se validan mediante hashes. `workspace/`, `artifacts/` y `docs/private/` están ignorados por Git porque contienen estado local, resultados y especificaciones de trabajo.

## Pruebas

Con Python y las dependencias de `requirements-authoring.txt`:

```bash
python3 -m unittest discover -s tests -v
```

El frontend se comprueba con:

```bash
cd frontend
npm ci
npm run build
```

La suite cubre importación lossless del caso, compilación determinista, IDs estables, comandos atómicos, validación, borradores, conflictos, tools del Agents SDK y el contrato de la geometría de referencia. La ejecución completa de Kratos se mantiene como operación explícita del worker.

## Decisiones deliberadas

No se añade un servidor MCP en este incremento: no hay consumidor MCP y las tools sólo las usa el agente del backend. Tampoco se introduce LangGraph; el flujo lineal del MVP se expresa con el Agents SDK y persistencia local. Se puede añadir una máquina de estados cuando aparezcan pausas y reanudaciones más complejas.
