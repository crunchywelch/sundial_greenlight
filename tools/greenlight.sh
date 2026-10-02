set -euo pipefail
cd ~/projects/sundial_greenlight
export SKIP_BOOTSTRAP=1
# shellcheck disable=SC1091
source dev_env.sh
python -m greenlight.main
