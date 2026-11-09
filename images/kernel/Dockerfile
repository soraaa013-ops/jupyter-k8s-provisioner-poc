FROM quay.io/jupyter/minimal-notebook:python-3.12

USER root
RUN pip install --no-cache-dir "gateway-provisioners==0.5.0" && \
    jupyter image-bootstrap install --languages=Python && \
    fix-permissions "${CONDA_DIR}" /home/jovyan

USER ${NB_UID}

CMD ["/usr/local/bin/bootstrap-kernel.sh"]

