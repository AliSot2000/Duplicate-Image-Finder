from typing import Union

import cupy as cp
import numpy as np

from fast_diff_py.child_processes import SecondLoopWorker
from fast_diff_py.cache import ImageCache
import pickle
import copy


squared_diff_generic = cp.ElementwiseKernel(
    in_params='T x, T y',
    out_params='T z',
    operation='z = (x - y) * (x - y)',
    name='squared_diff_generic')


def mse_gpu(image_a: cp.ndarray, image_b: cp.ndarray) -> float:
    """
    A GPU accelerated version of the mean squared error function.

    :param image_a: The first image to compare
    :param image_b: The second image to compare
    """
    sq_diff = squared_diff_generic(cp.array(image_a).astype("float"), cp.array(image_b).astype("float"))
    sum_diff = cp.sum(sq_diff)

    px_count = image_a.shape[0] * image_a.shape[1]
    return float(sum_diff / px_count)


class GPUCache(ImageCache):
    data: cp.ndarray

    def cache_from_numpy(self, array: np.ndarray[np.uint8]):
        """
        Set the data with a given old array
        """
        self.data = cp.asarray(array)


class SecondLoopGPUWorker(SecondLoopWorker):
    delta_fn = mse_gpu

    def prepare_cache(self, cache_key: Union[int, None]):
        if self.cache_key != cache_key and self.ram_cache is not None:
            self.cache_key = cache_key
            self.cache = pickle.loads(copy.deepcopy(self.ram_cache[self.cache_key]))

            # Create new objects
            if self.cache.x.offset == self.cache.y.offset:
                # Make the GPU cache
                gpu_cache = GPUCache(offset=self.cache.x.offset,
                                     size=self.cache.x.size,
                                     img_shape=self.cache.x.img_shape)
                gpu_cache.cache_from_numpy(self.cache.x.data)

                self.cache.x = gpu_cache
                self.cache.y = gpu_cache

            else:
                # Make the GPU cache
                gpu_cache_x = GPUCache(offset=self.cache.x.offset,
                                     size=self.cache.x.size,
                                     img_shape=self.cache.x.img_shape)
                gpu_cache_x.cache_from_numpy(self.cache.x.data)

                gpu_cache_y = GPUCache(offset=self.cache.y.offset,
                                     size=self.cache.y.size,
                                     img_shape=self.cache.y.img_shape)
                gpu_cache_y.cache_from_numpy(self.cache.y.data)


                self.cache.x = gpu_cache_x

