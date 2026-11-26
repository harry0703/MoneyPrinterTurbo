"""BYNEX AI Personal Studio.

Módulo local de voz clonada y avatares personalizados integrado en
MoneyPrinterTurbo. La voz se sintetiza en un proceso hijo con el entorno Python
de ``local-voice`` (PyTorch CPU + MeloTTS + OpenVoice V2) para no mezclar
dependencias con la aplicación.

Entradas principales::

    from app.services.personal_studio import voice_profiles, avatars, studio
    from app.services.personal_studio.jobs import StudioJobManager

Nada se publica en redes sociales: la exportación copia archivos locales y exige
una aprobación vigente del contenido.
"""

from app.services.personal_studio.security import (
    ConsentError,
    StudioError,
)
from app.services.personal_studio.studio import (
    ProjectStore,
    approval_state,
    approve,
    build_project,
    export,
    fingerprint,
    output_size,
)

__all__ = [
    "ConsentError",
    "ProjectStore",
    "StudioError",
    "approval_state",
    "approve",
    "build_project",
    "export",
    "fingerprint",
    "output_size",
]
