/**
 * PCCS Sonos Controller
 * Extracted from templates/index.html
 */
import { PCCS, getSocket } from './namespace.js';

let currentActiveSonosSpeaker = null;
let currentSonosState = {};
let progressInterval = null;

// Format seconds → MM:SS
function formatTime(seconds) {
  if (!seconds || isNaN(seconds)) return "0:00";
  const min = Math.floor(seconds / 60);
  const sec = Math.floor(seconds % 60);
  return `${min}:${sec.toString().padStart(2, '0')}`;
}

function updateSonosUI(state) {
    currentSonosState = state || {};

    const hasSpeaker = !!(state && state.speaker);
    const isEnabled = !!(state && state.enabled !== false);

    if (!hasSpeaker || !isEnabled) {
        // No devices or disabled: show disabled volume, leave other fields at initial '—' / 'Nothing playing' etc.
        const volSlider = document.getElementById('sonos-volume-slider');
        const volValue = document.getElementById('sonos-volume-value');
        if (volSlider) {
            volSlider.disabled = true;
            volSlider.value = 0;
        }
        if (volValue) volValue.textContent = '—';
        return;
    }
    
  const hasAlbumArt = !!(state && state.album_art && state.album_art.trim() !== '');

  // Album Art + Overlay
  const artEl = document.getElementById('sonos-album-art');
  const overlayEl = document.getElementById('sonos-overlay');
  if (artEl) {
    artEl.style.backgroundImage = hasAlbumArt 
      ? `url('${state.album_art}')` 
      : 'none';
    artEl.style.backgroundColor = hasAlbumArt ? '' : '#1f2937';
  }
  if (overlayEl) {
    overlayEl.style.opacity = hasAlbumArt ? '1' : '0';
  }

  document.getElementById('sonos-speaker-name').textContent = state.speaker || '—';

  // Track info
  document.getElementById('sonos-track').textContent = state.track || 'Nothing playing';
  document.getElementById('sonos-artist').textContent = state.artist || (state.album || '\u00A0');

  // Play/Pause icon
  const playIcon = document.getElementById('sonos-play-icon');
  if (playIcon) {
    playIcon.classList.toggle('fa-play', !state.is_playing);
    playIcon.classList.toggle('fa-pause', !!state.is_playing);
  }

  // Volume
  const volSlider = document.getElementById('sonos-volume-slider');
  const volValue = document.getElementById('sonos-volume-value');
  if (volSlider) {
    if (state.volume !== undefined && state.volume !== null) {
      volSlider.disabled = false;
      volSlider.value = state.volume;
      if (volValue) volValue.textContent = `${state.volume}%`;
    } else {
      volSlider.disabled = true;
      volSlider.value = 0;
      if (volValue) volValue.textContent = '—';
    }
  }

  // Mute
  const muteIcon = document.getElementById('sonos-mute-icon');
  if (muteIcon) {
    muteIcon.classList.toggle('fa-volume-mute', !!state.mute);
    muteIcon.classList.toggle('fa-volume-high', !state.mute);
  }

  // Progress Bar
  updateProgressBar(state);
}

function updateProgressBar(state) {
  const progressBar = document.getElementById('sonos-progress-bar');
  const elapsedEl = document.getElementById('sonos-time-elapsed');
  const remainingEl = document.getElementById('sonos-time-remaining');

  if (!progressBar) return;

  const position = state.position || 0;     // seconds elapsed
  const duration = state.duration || 0;     // total seconds

  if (duration <= 0) {
    progressBar.style.width = '0%';
    elapsedEl.textContent = '0:00';
    remainingEl.textContent = '-0:00';
    return;
  }

  const percent = Math.min(100, Math.max(0, (position / duration) * 100));
  progressBar.style.width = `${percent}%`;

  elapsedEl.textContent = formatTime(position);
  remainingEl.textContent = `-${formatTime(duration - position)}`;
}

// Optimistic live progress
function startProgressUpdater() {
  if (progressInterval) clearInterval(progressInterval);
  
  progressInterval = setInterval(() => {
    if (currentSonosState.is_playing && currentSonosState.duration) {
      currentSonosState.position = (currentSonosState.position || 0) + 1;
      if (currentSonosState.position > currentSonosState.duration) {
        currentSonosState.position = currentSonosState.duration;
      }
      updateProgressBar(currentSonosState);
    }
  }, 1000);
}

function sonosVolumeChange(volume) {
    const volValue = document.getElementById('sonos-volume-value');
    if (volValue) volValue.textContent = `${volume}%`;
    
    getSocket().emit('sonos_command', { 
        command: 'volume', 
        value: parseInt(volume) 
    });
}

function requestSonosState() {
    if (getSocket().connected) {
        getSocket().emit('sonos_request_state');
    } else {
        setTimeout(requestSonosState, 300);
    }
}

// ====================== SONOS CONTROLS ======================
function sonosCommand(command) {
    if (!getSocket().connected) {
        console.warn("Socket not connected");
        return;
    }

    getSocket().emit('sonos_command', { command: command });
    
    // Optimistic UI feedback
    if (command === 'playpause') {
        const playIcon = document.getElementById('sonos-play-icon');
        if (playIcon) {
            const isPlaying = playIcon.classList.contains('fa-pause');
            playIcon.classList.toggle('fa-play', isPlaying);
            playIcon.classList.toggle('fa-pause', !isPlaying);
        }
    }
}

function toggleSonosMute() {
    const muteBtn = document.getElementById('sonos-mute-btn');
    if (!muteBtn) return;
    
    getSocket().emit('sonos_command', { command: 'mute' });
    
    // Optimistic toggle
    const icon = document.getElementById('sonos-mute-icon');
    if (icon) {
        const isMuted = icon.classList.contains('fa-volume-mute');
        icon.classList.toggle('fa-volume-mute', !isMuted);
        icon.classList.toggle('fa-volume-high', isMuted);
    }
}

  PCCS.sonos = {
    updateSonosUI,
    startProgressUpdater,
    requestSonosState,
    sonosVolumeChange,
    sonosCommand,
    toggleSonosMute,
    register(socket) {
      socket.on('sonos_speakers', data => {
        if (data.current) currentActiveSonosSpeaker = data.current;
      });
      socket.on('sonos_update', state => {
        if (!state) return;
        if (currentActiveSonosSpeaker && state.speaker && state.speaker !== currentActiveSonosSpeaker) return;
        updateSonosUI(state);
      });
    },
    bindProgressSeek() {
      const el = document.getElementById('sonos-progress-container');
      if (!el) return;
      el.addEventListener('click', function (e) {
        const rect = this.getBoundingClientRect();
        const percent = (e.clientX - rect.left) / rect.width;
        getSocket().emit('sonos_command', { command: 'seek', value: percent });
      });
    },
  };
