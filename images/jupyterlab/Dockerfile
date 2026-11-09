FROM quay.io/jupyter/base-notebook:python-3.12

ARG KERNEL_IMAGE=jupyter-kernel-poc:0.1.0
ARG GATEWAY_PROVISIONERS_VERSION=0.5.0

USER root
RUN pip install --no-cache-dir "gateway-provisioners[k8s]==${GATEWAY_PROVISIONERS_VERSION}" && \
    jupyter k8s-spec install \
      --image-name "${KERNEL_IMAGE}" \
      --kernel-name k8s_python \
      --display-name "Kubernetes Python" && \
    fix-permissions "${CONDA_DIR}" /home/jovyan

USER ${NB_UID}

