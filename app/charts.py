"""
Server-side chart generation module.
Generates Chart.js-style charts as Base64 PNG images for PDF embedding.
"""

import base64
import io
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np

# Chart.js default color palette (for consistency with frontend)
CHARTJS_COLORS = [
    '#36A2EB',  # Blue
    '#FF6384',  # Red/Pink
    '#FFCE56',  # Yellow
    '#4BC0C0',  # Teal
    '#9966FF',  # Purple
    '#FF9F40',  # Orange
    '#C9CBCF',  # Grey
    '#7CB342',  # Green
]

@dataclass
class ChartStyle:
    """Configuration for Chart.js-like styling."""
    figure_width: float = 10
    figure_height: float = 6
    dpi: int = 150
    font_family: str = 'sans-serif'
    title_fontsize: int = 16
    label_fontsize: int = 12
    tick_fontsize: int = 10
    grid_alpha: float = 0.3
    grid_color: str = '#E0E0E0'
    background_color: str = '#FFFFFF'
    border_color: str = '#DDDDDD'


def _apply_chartjs_style(ax: plt.Axes, style: ChartStyle) -> None:
    """Apply Chart.js-like styling to a matplotlib axes."""
    # Grid styling (Chart.js default)
    ax.grid(True, axis='y', alpha=style.grid_alpha, color=style.grid_color, linestyle='-')
    ax.set_axisbelow(True)
    
    # Remove top and right spines (Chart.js style)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(style.border_color)
    ax.spines['bottom'].set_color(style.border_color)
    
    # Tick styling
    ax.tick_params(axis='both', labelsize=style.tick_fontsize, colors='#666666')


def _fig_to_base64(fig: plt.Figure, dpi: int = 150) -> str:
    """Convert matplotlib figure to Base64 PNG string."""
    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format='png',
        dpi=dpi,
        bbox_inches='tight',
        facecolor='white',
        edgecolor='none',
        pad_inches=0.2
    )
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    buffer.close()
    plt.close(fig)
    return f"data:image/png;base64,{image_base64}"


def generate_bar_chart(
    labels: List[str],
    datasets: List[Dict[str, Any]],
    title: str = "",
    x_label: str = "",
    y_label: str = "",
    style: Optional[ChartStyle] = None,
    horizontal: bool = False,
    stacked: bool = False,
) -> str:
    """Generate a bar chart matching Chart.js aesthetics."""
    style = style or ChartStyle()
    
    fig, ax = plt.subplots(figsize=(style.figure_width, style.figure_height))
    fig.patch.set_facecolor(style.background_color)
    
    x = np.arange(len(labels))
    num_datasets = len(datasets)
    bar_width = 0.8 / num_datasets if not stacked else 0.8
    
    for i, dataset in enumerate(datasets):
        data = dataset['data']
        label = dataset.get('label', f'Dataset {i+1}')
        color = dataset.get('color', CHARTJS_COLORS[i % len(CHARTJS_COLORS)])
        edge_color = dataset.get('border_color', color)
        
        if stacked:
            bottom = np.zeros(len(labels)) if i == 0 else np.sum(
                [ds['data'] for ds in datasets[:i]], axis=0
            )
            offset = x
        else:
            offset = x + (i - num_datasets / 2 + 0.5) * bar_width
            bottom = None
            
        if horizontal:
            bars = ax.barh(
                offset,
                data,
                bar_width if not stacked else 0.8,
                label=label,
                color=color,
                edgecolor=edge_color,
                linewidth=1,
                alpha=0.85,
                left=bottom,
            )
        else:
            bars = ax.bar(
                offset,
                data,
                bar_width if not stacked else 0.8,
                label=label,
                color=color,
                edgecolor=edge_color,
                linewidth=1,
                alpha=0.85,
                bottom=bottom,
            )
    
    # Axis labels and legend
    if horizontal:
        ax.set_yticks(x)
        ax.set_yticklabels(labels, fontsize=style.tick_fontsize)
        ax.set_xlabel(y_label, fontsize=style.label_fontsize, color='#666666')
    else:
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=style.tick_fontsize, rotation=45 if len(labels) > 6 else 0, ha='right' if len(labels) > 6 else 'center')
        ax.set_ylabel(y_label, fontsize=style.label_fontsize, color='#666666')
    
    if title:
        ax.set_title(title, fontsize=style.title_fontsize, fontweight='bold', color='#333333', pad=20)
        
    if num_datasets > 1 or (datasets and datasets[0].get('label')):
        ax.legend(loc='upper right', frameon=False, fontsize=style.tick_fontsize)
        
    _apply_chartjs_style(ax, style)
    fig.tight_layout()
    
    return _fig_to_base64(fig, style.dpi)
