# Isaac Sim with this workspace; the entrypoint runs the configured scenario.
#
# The workspace is copied in so the image runs on its own (CI, deployment);
# docker-compose.yml mounts the checkout over it for development.
ARG ISAAC_SIM_IMAGE=nvcr.io/nvidia/isaac-sim:6.2.0
FROM ${ISAAC_SIM_IMAGE}

ENV ACCEPT_EULA=Y \
    PRIVACY_CONSENT=N \
    RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# Cache and log directories that compose mounts as volumes, created here so
# fresh volumes take the runtime user's ownership. SimulationApp runs Kit in
# portable mode, so its shader cache is the one under kit/.
USER root
RUN mkdir -p \
        /isaac-sim/kit/cache \
        /isaac-sim/.cache \
        /isaac-sim/.nv/ComputeCache \
        /isaac-sim/.nvidia-omniverse/logs \
        /isaac-sim/.local/share/ov/data \
        /workspace/out \
    && chown -R 1234:1234 \
        /isaac-sim/kit/cache \
        /isaac-sim/.cache \
        /isaac-sim/.nv \
        /isaac-sim/.nvidia-omniverse \
        /isaac-sim/.local \
        /workspace
USER 1234:1234

COPY --chown=1234:1234 . /workspace
WORKDIR /workspace

ENTRYPOINT ["/workspace/sim/run.sh"]
