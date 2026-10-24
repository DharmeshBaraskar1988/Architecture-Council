# Solution catalog entry format

One file per capability. Each candidate has a `type`:
`owned` · `cloud_managed` · `saas` · `open_source` · `none` (no native service on that provider).

Pages (`pages:`), each on an allowlisted domain (`config/sources.yaml`). `council verify` fetches every one:
- `official`: the product's official documentation or repository page
- `pricing`: the official pricing page (not needed for open source)
- `terms`: service or data-use terms for services; the licence text for open source
- `sla`: the published service level agreement (services with `sla: true`)

Gate fields, recorded by a person from the pages above:
- `licence`: SPDX id for open source, the model's licence id for model weights, or `proprietary` for services
- `lifecycle`: `ga` · `preview` · `deprecated` · `unknown`
- `sla`: `true` (published) · `contract` (only in an enterprise contract) · `false` (none) · `unknown`
- `official_api`: `true` · `false` (no official API agreement for this use) · `unknown`
- `data_terms`: `ok` (customer data not used to train or improve the service by default) · `review` · `unknown`
- `repo`: `owner/name` on GitHub (open source): the verifier reads licence, archive state and last push from the GitHub API
- `model`: Hugging Face model id (model weights): the verifier reads the licence from the model card
- `note`: anything the reviewer should know

What the verifier decides by code (`data/catalog/verification.json`, merged into the gate):
- `verified`: every listed page was fetched from an allowlisted domain and has real text
- `licence` and `maintained` (last push within 12 months, not archived) from GitHub or Hugging Face, overriding the recorded value
- `lifecycle: preview` when the official page's title says preview or beta
