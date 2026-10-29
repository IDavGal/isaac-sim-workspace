# Isaac Sim with this workspace; the entrypoint runs sim/main.py.
#
# Built by `docker/sim.sh build` for the host user's ids, so files the container
# writes to the mounted checkout belong to that user. The workspace is copied in so
# the image runs on its own (CI, deployment); docker-compose.yml mounts the checkout
# over it for development.
ARG ISAAC_SIM_IMAGE=nvcr.io/nvidia/isaac-sim:6.2.0
# hadolint ignore=DL3026  # the registry is in the build argument, nvcr.io by default
FROM ${ISAAC_SIM_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG USER_ID=1000
ARG GROUP_ID=1000

LABEL org.opencontainers.image.title="isaac-sim-workspace" \
      org.opencontainers.image.description="Isaac Sim 6.2 with the ROS 2 bridge, running sim/main.py"

# OmniHub, the local cache for remote assets that Kit's client launches: the base
# image only lets it detect a running Hub (HUB__ARGS__DETECT_ONLY), so the launch
# always fails and Kit logs ~40 retry warnings at startup, and its cache dir
# /var/cache/hub belongs to the base image's user, not `sim`. Here the Hub starts,
# on dynamic localhost ports, with its cache in the container: instances of one
# user share the cache volumes, and each container starts its own Hub.
ENV PRIVACY_CONSENT=N \
    RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    HUB__ARGS__DETECT_ONLY=false \
    HUB__CACHE__PATH=/tmp/hub-cache

USER root
COPY docker/setup_user.sh /tmp/setup_user.sh
RUN bash /tmp/setup_user.sh "${USER_ID}" "${GROUP_ID}" && rm /tmp/setup_user.sh
USER sim

COPY --chown=${USER_ID}:${GROUP_ID} . /workspace
WORKDIR /workspace

# Smoke test as the runtime user: the earlier steps ran as root and would hide
# permission problems. --help returns before Isaac Sim starts.
RUN /workspace/sim/run.sh --help >/dev/null

# Healthy once Kit is ready, which both experiences log ("App is loaded." is only
# logged by the editor). Replaces the base image's check, which reads the logs in
# HOME, where SimulationApp (Kit in portable mode) does not write them.
HEALTHCHECK --start-period=180s --interval=30s --timeout=10s --retries=3 \
    CMD ["bash", "-c", "log=$(ls -t /isaac-sim/kit/logs/Kit/*/*/kit_*.log | head -1) && grep -Eq '[]] app ready$' \"$log\""]

ENTRYPOINT ["/workspace/sim/run.sh"]
