// KufPlay: RTS camera pawn, player controller and game mode for the Kingdom Under Fire port.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "KufPlay.generated.h"

class AKufUnit;
class UCameraComponent;
class USpringArmComponent;

UCLASS()
class AKufRtsPawn : public APawn
{
	GENERATED_BODY()

public:
	AKufRtsPawn();

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USpringArmComponent> Boom;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UCameraComponent> Camera;
};

UCLASS()
class AKufPlayerController : public APlayerController
{
	GENERATED_BODY()

public:
	AKufPlayerController();

	virtual void SetupInputComponent() override;
	virtual void PlayerTick(float DeltaTime) override;

	TArray<TWeakObjectPtr<AKufUnit>> Selected;

private:
	void OnSelect();
	void OnCommand();
	void OnSelectAll();
	void Zoom(float Delta);
	void ZoomInKey();
	void ZoomOutKey();
	void ClearSelection();
};

UCLASS()
class AKufGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AKufGameMode();

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	void RunSelfTestStep(float DeltaSeconds);

	bool bSelfTest = false;
	float SelfTestTime = 0.0f;
	bool bSelfTestOrdered = false;
	int32 StartPlayers = 0;
	int32 StartEnemies = 0;
};
