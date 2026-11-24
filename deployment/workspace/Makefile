.PHONY: install check build up stop status logs deploy-bot deploy-core rollback snapshot
OPS = remote-vibecoding
install:
	$(MAKE) -C vibecoding-core install
check:
	$(MAKE) -C vibecoding-core check
build:
	$(OPS) build
up:
	$(OPS) up
stop:
	$(OPS) stop
status:
	$(OPS) status
logs:
	$(OPS) logs
deploy-bot:
	$(OPS) deploy-bot
deploy-core:
	$(OPS) deploy-core
rollback:
	$(OPS) rollback-bot
snapshot:
	$(OPS) snapshot
