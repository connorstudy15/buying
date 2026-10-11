# Amazon Berkeley Objects — demo catalog

Data and source images © Amazon.com. Dataset builders: Matthieu Guillaumin,
Thomas Dideriksen, Kenan Deng, Himanshu Arora, Jasmine Collins and Jitendra Malik.

Source: https://amazon-berkeley-objects.s3.amazonaws.com/index.html

License: https://creativecommons.org/licenses/by/4.0/ (full text in this folder).

Changes: filtered and sampled listings, grouped into 24 Chinese retail categories
with at most 30 products each, HTML removed, units normalized, fields mapped to
Product/Sku. Original names/descriptions retain source language. Official image
paths are linked without modifying the source images. Synthetic CNY prices,
inventory and shipping rules were added for demonstration and are not Amazon
offers. Marketplace country is retained as source locale, not manufacturing origin.
No endorsement is implied.

Metadata archive SHA256:
`b7f7ceacb328fa5ab6e143b88e1f948443a877cfc95b67ff09c8ebabd50644e3`.

The full original archive and raw sample are cached locally under `.tmp/abo/`;
only the transformed catalog, report and attribution are included in deployment.
