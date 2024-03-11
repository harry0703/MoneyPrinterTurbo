CURRENT_DIR=$(pwd)
echo "***** Current directory: $CURRENT_DIR *****"
export PYTHONPATH="${CURRENT_DIR}:$PYTHONPATH"
streamlit run ./webui/Main.py