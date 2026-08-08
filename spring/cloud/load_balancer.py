"""
负载均衡模块
提供多种负载均衡算法
"""
import random
import logging
from typing import Dict, List, Any, Optional
from spring.cloud import discovery

logger = logging.getLogger("Spring.Cloud.LoadBalancer")


class LoadBalancer:
    """负载均衡器"""
    
    _instance = None
    _lock = __import__('threading').Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, strategy: str = "round_robin"):
        if hasattr(self, '_initialized'):
            return
        self.strategy = strategy
        self._round_robin_index: Dict[str, int] = {}
        self._initialized = True
    
    def get_instances(self, service_name: str) -> List[Dict[str, Any]]:
        """
        获取服务实例列表
        
        Args:
            service_name: 服务名称
        
        Returns:
            实例列表
        """
        return discovery.nacos_client.get_service_instances(service_name)
    
    def select_instance(self, instances: List[Dict[str, Any]], 
                        strategy: str = None) -> Dict[str, Any]:
        """
        根据负载均衡策略选择实例
        
        Args:
            instances: 实例列表
            strategy: 策略名称（round_robin/random/weighted）
        
        Returns:
            选中的实例
        """
        if not instances:
            raise Exception("No instances available")
        
        strategy = strategy or self.strategy
        
        # 过滤健康实例
        healthy_instances = [i for i in instances if i.get('healthy', True)]
        if not healthy_instances:
            # 如果没有健康实例，返回第一个实例
            return instances[0]
        
        if strategy == "round_robin":
            return self._round_robin(healthy_instances)
        elif strategy == "random":
            return self._random(healthy_instances)
        elif strategy == "weighted":
            return self._weighted(healthy_instances)
        else:
            return self._round_robin(healthy_instances)
    
    def _round_robin(self, instances: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        轮询策略
        
        Args:
            instances: 实例列表
        
        Returns:
            选中的实例
        """
        # 生成一个唯一的key用于追踪索引
        key = '|'.join(
            sorted(f"{item.get('ip', '')}:{item.get('port', '')}" for item in instances)
        )
        
        if key not in self._round_robin_index:
            self._round_robin_index[key] = 0
        
        index = self._round_robin_index[key]
        instance = instances[index % len(instances)]
        self._round_robin_index[key] = index + 1
        
        return instance
    
    def _random(self, instances: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        随机策略
        
        Args:
            instances: 实例列表
        
        Returns:
            选中的实例
        """
        return random.choice(instances)
    
    def _weighted(self, instances: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        加权随机策略
        
        Args:
            instances: 实例列表
        
        Returns:
            选中的实例
        """
        total_weight = sum(instance.get('weight', 1) for instance in instances)
        
        if total_weight <= 0:
            return random.choice(instances)
        
        random_weight = random.uniform(0, total_weight)
        
        current_weight = 0
        for instance in instances:
            current_weight += instance.get('weight', 1)
            if current_weight >= random_weight:
                return instance
        
        return instances[-1]
    
    def set_strategy(self, strategy: str):
        """
        设置负载均衡策略
        
        Args:
            strategy: 策略名称
        """
        self.strategy = strategy


# 创建全局负载均衡器实例
load_balancer = LoadBalancer()
