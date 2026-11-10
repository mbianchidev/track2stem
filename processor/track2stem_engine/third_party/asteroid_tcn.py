# Adapted from asteroid-team/asteroid eebbc76c731bfeeee355344c97a3d462bf795d7b.
# Copyright (c) 2019 Pariente Manuel. MIT; see ASTEROID-LICENSE.
# Inference-only Conv-TasNet primitives, without obsolete training dependencies.
import torch
from torch import nn


class GlobalNorm(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.gamma = nn.Parameter(torch.ones(channels))
        self.beta = nn.Parameter(torch.zeros(channels))

    def forward(self, value):
        mean = value.mean(dim=(1, 2), keepdim=True)
        variance = value.var(dim=(1, 2), keepdim=True, unbiased=False)
        normalized = (value - mean) / torch.sqrt(variance + 1e-8)
        return normalized * self.gamma[None, :, None] + self.beta[None, :, None]


class ConvBlock(nn.Module):
    def __init__(self, dilation):
        super().__init__()
        self.shared_block = nn.Sequential(
            nn.Conv1d(256, 1024, 1), nn.PReLU(), GlobalNorm(1024),
            nn.Conv1d(1024, 1024, 3, padding=dilation, dilation=dilation, groups=1024),
            nn.PReLU(), GlobalNorm(1024),
        )
        self.res_conv = nn.Conv1d(1024, 256, 1)
        self.skip_conv = nn.Conv1d(1024, 256, 1)

    def forward(self, value):
        hidden = self.shared_block(value)
        return self.res_conv(hidden), self.skip_conv(hidden)


class TemporalMasker(nn.Module):
    def __init__(self, channels=2050):
        super().__init__()
        self.bottleneck = nn.Sequential(GlobalNorm(channels), nn.Conv1d(channels, 256, 1))
        self.TCN = nn.ModuleList([ConvBlock(2 ** block) for _ in range(4) for block in range(6)])
        self.mask_net = nn.Sequential(nn.PReLU(), nn.Conv1d(256, channels * 2, 1))
        self.channels = channels

    def forward(self, encoded):
        value = self.bottleneck(encoded)
        skip = torch.zeros_like(value)
        for layer in self.TCN:
            residual, output = layer(value)
            value = value + residual
            skip = skip + output
        return self.mask_net(skip).reshape(encoded.shape[0], 2, self.channels, encoded.shape[-1])
