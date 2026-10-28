from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import OrderStateSerializer
from .services.order_states import change_order_state


class AdminOrderStateView(APIView):
    """Изменение статуса заказа администратором."""

    permission_classes = [IsAuthenticated, IsAdminUser]

    def patch(self, request, pk):
        serializer = OrderStateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order, changed = change_order_state(
            user=request.user,
            order_id=pk,
            state=serializer.validated_data["state"],
        )

        return Response(
            {
                "Status": True,
                "Order": order.pk,
                "State": order.state,
                "Changed": changed,
            },
            status=status.HTTP_200_OK,
        )