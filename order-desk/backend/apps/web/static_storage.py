"""Hash native ES-module references along with their dependency files."""

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class ModuleManifestStorage(ManifestStaticFilesStorage):
    support_js_module_import_aggregation = True
