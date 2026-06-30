# Custom GPT setup

## GPT instructions

Paste the complete contents of `custom-gpt-instructions.md` into the Custom
GPT Instructions field.

## Action

- Authentication type: API Key
- Authentication mode: Bearer
- API key value: copy the complete contents of
  `/home/admin/ai/runtime/novel-actions/action.token`
- OpenAPI import URL:
  `https://iz5ts314xq7lzp4t07pfmoz.tail04405f.ts.net/openapi.json`
- Privacy policy URL:
  `https://iz5ts314xq7lzp4t07pfmoz.tail04405f.ts.net/privacy`

Keep this GPT private. Do not expose or paste the Bearer token into chat.

## First test

Ask the GPT to call `getNovelWorkflowDefaults`. A successful response includes
the three allowed Fanqie accounts and the 12-to-3 workflow. Do not test draft
upload until a new book has been manually created on Fanqie and the first three
chapters have been reviewed and approved.
