class BticinoC100XCard extends HTMLElement {
  setConfig(config) {
    for (const key of ["camera_entity", "start_entity", "end_entity", "release_entity"]) {
      if (!config[key]) throw new Error(`Missing ${key}`);
    }
    this.config = config;
    this.owner = crypto.randomUUID();
    this.attachShadow({ mode: "open" });
    this.render();
  }

  set hass(value) {
    this._hass = value;
    if (this.stream) {
      this.stream.hass = value;
      this.stream.stateObj = value.states[this.config.camera_entity];
    }
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { overflow:hidden; } .media { background:#111; min-height:240px; position:relative; }
        .media img { display:block; width:100%; min-height:240px; object-fit:contain; }
        .transport { position:absolute; width:1px; height:1px; opacity:0; overflow:hidden; }
        .controls { display:flex; gap:8px; padding:12px; flex-wrap:wrap; }
        button { border:0; border-radius:18px; padding:9px 14px; cursor:pointer; }
        .release { margin-left:auto; color:var(--error-color); }
        .status { padding:0 12px 12px; color:var(--secondary-text-color); }
      </style>
      <ha-card header="Front door"><div class="media"></div><div class="controls">
        <button data-action="start">Start</button><button data-action="end">End</button>
        <button data-action="microphone">Microphone</button>
        <button class="release" data-action="release">Release door</button>
      </div><div class="status">Listen-only · microphone off</div></ha-card>`;
    this.shadowRoot.querySelectorAll("button").forEach((button) =>
      button.addEventListener("click", () => this.action(button.dataset.action))
    );
  }

  async action(action) {
    const entity = { start: this.config.start_entity, end: this.config.end_entity,
      release: this.config.release_entity }[action];
    try {
      if (entity) {
        await this._hass.callService("button", "press", { entity_id: entity });
        if (action === "start") this.showStream();
        if (action === "end") {
          await this.disableMicrophone();
          this.hideStream();
        }
      } else if (this.peer) {
        await this.disableMicrophone();
      } else {
        await this.enableMicrophone();
      }
    } catch (error) { this.setStatus(error.message || String(error), true); }
  }

  showStream() {
    if (this.stream) return;
    this.stream = document.createElement("ha-camera-stream");
    this.stream.className = "transport";
    this.stream.controls = false;
    this.stream.muted = false;
    this.stream.hass = this._hass;
    this.stream.stateObj = this._hass.states[this.config.camera_entity];
    const state = this._hass.states[this.config.camera_entity];
    const token = state?.attributes?.access_token;
    const query = token ? `?token=${encodeURIComponent(token)}` : "";
    this.image = document.createElement("img");
    this.image.alt = "Live front-door video";
    this.image.src = `/api/camera_proxy_stream/${this.config.camera_entity}${query}`;
    this.image.addEventListener("load", () =>
      this.setStatus("Live video over Home Assistant · microphone off"));
    this.image.addEventListener("error", () =>
      this.setStatus("Live video connection failed", true));
    const media = this.shadowRoot.querySelector(".media");
    media.append(this.stream, this.image);
    this.setStatus("Connecting live video…");
  }

  hideStream() {
    if (!this.stream) return;
    this.stream.remove();
    this.image?.remove();
    this.stream = null;
    this.image = null;
  }

  disconnectedCallback() {
    this.disableMicrophone().catch(() => {});
    this.hideStream();
  }

  async enableMicrophone() {
    // Permission is intentionally requested only from this explicit click.
    const media = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    const peer = new RTCPeerConnection();
    media.getAudioTracks().forEach((track) => peer.addTrack(track, media));
    await peer.setLocalDescription(await peer.createOffer());
    await new Promise((resolve) => {
      if (peer.iceGatheringState === "complete") return resolve();
      peer.addEventListener("icegatheringstatechange", () =>
        peer.iceGatheringState === "complete" && resolve());
    });
    try {
      const result = await this._hass.connection.sendMessagePromise({
        type: "bticino_c100x/microphone/negotiate", entry_id: this.entryId,
        owner: this.owner, offer: peer.localDescription.sdp
      });
      await peer.setRemoteDescription({ type: "answer", sdp: result.answer });
      this.peer = peer; this.microphoneMedia = media;
      this.setStatus("Microphone on");
    } catch (error) {
      media.getTracks().forEach((track) => track.stop()); peer.close(); throw error;
    }
  }

  async disableMicrophone() {
    if (!this.peer) return;
    // Server disables SRTP transmission first; capture stops only after acknowledgement.
    await this._hass.connection.sendMessagePromise({ type: "bticino_c100x/microphone/set",
      entry_id: this.entryId, owner: this.owner, enabled: false });
    this.microphoneMedia.getTracks().forEach((track) => track.stop());
    this.peer.close(); this.peer = null; this.microphoneMedia = null;
    this.setStatus("Listen-only · microphone off");
  }

  setStatus(text, error = false) {
    const status = this.shadowRoot.querySelector(".status");
    status.textContent = text; status.style.color = error ? "var(--error-color)" : "";
  }

  get entryId() {
    const entryId = this.config.entry_id || this._hass?.entities?.[this.config.camera_entity]?.config_entry_id;
    if (!entryId) throw new Error("Unable to resolve the BTicino config entry");
    return entryId;
  }

  getCardSize() { return 5; }
  static getStubConfig() { return {}; }
}

customElements.define("bticino-c100x-card", BticinoC100XCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "bticino-c100x-card", name: "BTicino C100X Intercom",
  description: "User-initiated Classe 100X video, audio and controls" });
