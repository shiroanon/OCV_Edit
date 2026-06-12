<script lang="ts">
	let { value = 'ease_in_out', onChange }: { value?: string; onChange?: (v: string) => void } = $props();

	const presets = [
		{ label: 'Linear', value: 'linear' },
		{ label: 'Ease In', value: 'ease_in' },
		{ label: 'Ease Out', value: 'ease_out' },
		{ label: 'Ease In-Out', value: 'ease_in_out' },
		{ label: 'Snap', value: 'snap' },
	];

	let selected = $state(value);
	let cpx1 = $state(0.25);
	let cpy1 = $state(0.1);
	let cpx2 = $state(0.25);
	let cpy2 = $state(1.0);

	function selectPreset(v: string) {
		selected = v;
		onChange?.(v);
		switch (v) {
			case 'linear': cpx1 = 0; cpy1 = 0; cpx2 = 1; cpy2 = 1; break;
			case 'ease_in': cpx1 = 0.42; cpy1 = 0; cpx2 = 1; cpy2 = 1; break;
			case 'ease_out': cpx1 = 0; cpy1 = 0; cpx2 = 0.58; cpy2 = 1; break;
			case 'ease_in_out': cpx1 = 0.42; cpy1 = 0; cpx2 = 0.58; cpy2 = 1; break;
			case 'snap': cpx1 = 0.1; cpy1 = 1.5; cpx2 = 0.9; cpy2 = -0.5; break;
		}
	}

	const W = 120;
	const H = 120;
	const PAD = 10;

	let dragging: 'p1' | 'p2' | null = null;

	function toCanvas(px: number, py: number) {
		return { x: PAD + px * (W - 2 * PAD), y: PAD + (1 - py) * (H - 2 * PAD) };
	}

	function fromCanvas(cx: number, cy: number) {
		return { px: (cx - PAD) / (W - 2 * PAD), py: 1 - (cy - PAD) / (H - 2 * PAD) };
	}

	function handleMouseDown(e: MouseEvent) {
		const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
		const cx = e.clientX - rect.left;
		const cy = e.clientY - rect.top;
		const p1 = toCanvas(cpx1, cpy1);
		const p2 = toCanvas(cpx2, cpy2);
		const d1 = Math.sqrt((cx - p1.x) ** 2 + (cy - p1.y) ** 2);
		const d2 = Math.sqrt((cx - p2.x) ** 2 + (cy - p2.y) ** 2);
		if (d1 < 14) dragging = 'p1';
		else if (d2 < 14) dragging = 'p2';
	}

	function handleMouseMove(e: MouseEvent) {
		if (!dragging) return;
		const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
		const cx = Math.max(PAD, Math.min(W - PAD, e.clientX - rect.left));
		const cy = Math.max(PAD, Math.min(H - PAD, e.clientY - rect.top));
		const { px, py } = fromCanvas(cx, cy);
		if (dragging === 'p1') { cpx1 = Math.max(0, Math.min(1, px)); cpy1 = py; }
		else { cpx2 = Math.max(0, Math.min(1, px)); cpy2 = py; }
		const v = `cubic-bezier(${cpx1.toFixed(3)}, ${cpy1.toFixed(3)}, ${cpx2.toFixed(3)}, ${cpy2.toFixed(3)})`;
		selected = v;
		onChange?.(v);
	}

	function handleMouseUp() { dragging = null; }

	let canvasEl: HTMLCanvasElement | undefined = $state();

	$effect(() => {
		if (!canvasEl) return;
		const ctx = canvasEl.getContext('2d')!;
		const dpr = window.devicePixelRatio || 1;
		canvasEl.width = W * dpr;
		canvasEl.height = H * dpr;
		ctx.scale(dpr, dpr);

		ctx.clearRect(0, 0, W, H);

		// Background
		ctx.fillStyle = '#181825';
		ctx.fillRect(0, 0, W, H);

		// Grid
		ctx.strokeStyle = '#333';
		ctx.lineWidth = 0.5;
		for (let i = 0; i <= 4; i++) {
			const t = i / 4;
			const p = toCanvas(t, 0);
			ctx.beginPath(); ctx.moveTo(p.x, PAD); ctx.lineTo(p.x, H - PAD); ctx.stroke();
			ctx.beginPath(); ctx.moveTo(PAD, p.y); ctx.lineTo(W - PAD, p.y); ctx.stroke();
		}

		// Diagonal reference
		ctx.strokeStyle = '#2a2a4a';
		ctx.lineWidth = 1;
		const p0 = toCanvas(0, 0);
		const p3 = toCanvas(1, 1);
		ctx.beginPath(); ctx.moveTo(p0.x, p0.y); ctx.lineTo(p3.x, p3.y); ctx.stroke();

		// Bezier curve
		const p1 = toCanvas(cpx1, cpy1);
		const p2 = toCanvas(cpx2, cpy2);

		ctx.strokeStyle = '#6a4aff';
		ctx.lineWidth = 2.5;
		ctx.beginPath();
		ctx.moveTo(p0.x, p0.y);
		ctx.bezierCurveTo(p1.x, p1.y, p2.x, p2.y, p3.x, p3.y);
		ctx.stroke();

		// Control lines
		ctx.strokeStyle = '#4a4a8a';
		ctx.lineWidth = 1;
		ctx.setLineDash([3, 3]);
		ctx.beginPath(); ctx.moveTo(p0.x, p0.y); ctx.lineTo(p1.x, p1.y); ctx.stroke();
		ctx.beginPath(); ctx.moveTo(p3.x, p3.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
		ctx.setLineDash([]);

		// Control points
		ctx.fillStyle = '#8a6aff';
		ctx.beginPath(); ctx.arc(p1.x, p1.y, 5, 0, Math.PI * 2); ctx.fill();
		ctx.fillStyle = '#ff6a8a';
		ctx.beginPath(); ctx.arc(p2.x, p2.y, 5, 0, Math.PI * 2); ctx.fill();
	});

	// Sync external value changes
	$effect(() => {
		if (value !== selected) {
			selected = value;
			if (!value.startsWith('cubic-bezier')) {
				selectPreset(value);
			}
		}
	});
</script>

<div class="easing-editor">
	<div class="preset-row">
		{#each presets as p}
			<button
				class="preset-btn"
				class:active={selected === p.value}
				onclick={() => selectPreset(p.value)}
			>{p.label}</button>
		{/each}
	</div>
	<canvas
		bind:this={canvasEl}
		width={W}
		height={H}
		style="width: {W}px; height: {H}px; cursor: pointer; border-radius: 6px;"
		onmousedown={handleMouseDown}
		onmousemove={handleMouseMove}
		onmouseup={handleMouseUp}
		onmouseleave={handleMouseUp}
		role="img"
		aria-label="Easing curve editor"
	/>
	<div class="value-display">{selected}</div>
</div>

<style>
	.easing-editor {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
	}
	.preset-row {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
		justify-content: center;
	}
	.preset-btn {
		background: #333;
		border: 1px solid #555;
		color: #aaa;
		padding: 2px 6px;
		border-radius: 3px;
		font-size: 10px;
		cursor: pointer;
	}
	.preset-btn.active {
		background: #4a3a8a;
		border-color: #6a4aff;
		color: #fff;
	}
	.value-display {
		font-size: 9px;
		color: #666;
		font-family: monospace;
		word-break: break-all;
		text-align: center;
		max-width: 100%;
	}
</style>
