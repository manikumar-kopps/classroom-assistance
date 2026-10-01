# Microsoft Foundry Flask — syllabus demo

## Setup
1. Copy `.env.example` to `.env`.
2. Replace only the endpoint/key/deployment values with your own Azure values.
3. `python -m venv .venv`
4. `source .venv/bin/activate` (Windows: `.venv\\Scripts\\activate`)
5. `pip install -r requirements.txt`
6. `python app.py`
7. Open http://127.0.0.1:5000

## Important
The Azure OpenAI endpoint should look like:
https://YOUR-RESOURCE.openai.azure.com
Do NOT put `/api/projects/...` into AZURE_OPENAI_ENDPOINT.

The Foundry project endpoint is a different endpoint used by the Foundry SDK:
https://YOUR-RESOURCE.services.ai.azure.com/api/projects/YOUR-PROJECT

The app keeps keys server-side in `.env`.

## Modules
- Text chat / Responses API
- Text analysis: sentiment, keywords, entities, summary
- Vision: image upload + analysis
- Image generation with a FLUX-1.1-pro deployment in Microsoft Foundry
- Speech-to-Text
- Content Understanding endpoint wrapper
- Agent-style demo
- Health/configuration check at /health

## Notes
Model names are deployment names in your Azure resource. Image generation uses the Foundry resource endpoint and key configured for `CONTENT_ENDPOINT` and `CONTENT_API_KEY` and requires a FLUX-1.1-pro deployment; set `IMAGE_MODEL_DEPLOYMENT` to that deployment name. Vision requires a vision-capable deployment. Content Understanding analyzer names depend on the analyzers enabled/available in your resource.
